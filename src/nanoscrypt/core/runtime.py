import hashlib
import subprocess
import sys
import time
import venv
from dataclasses import dataclass
from pathlib import Path

import structlog

from nanoscrypt.config.settings import settings
from nanoscrypt.models.tool import GeneratedTool
from nanoscrypt.utils.filesystem import ensure_directory, remove_directory

logger = structlog.get_logger()


@dataclass
class ExecutionResult:
    stdout: str
    stderr: str
    return_code: int
    runtime_ms: int
    timed_out: bool
    workspace_path: Path


class RuntimeManager:
    """Manages isolated workspaces and shared virtual environments to optimize tool execution latency."""

    def __init__(self, workspace_root: Path | str, timeout_seconds: int = 30):
        self.workspace_root = Path(workspace_root)
        self.timeout_seconds = timeout_seconds
        self.venv_cache_dir = Path(settings.runtime.venv_cache_dir)
        ensure_directory(self.workspace_root)
        ensure_directory(self.venv_cache_dir)

    def get_session_workspace(self, session_id: str) -> Path:
        """Returns the isolated path for a specific session's workspace."""
        return self.workspace_root / session_id

    def get_dependencies_hash(self, requirements: list[str]) -> str:
        """Generates a stable hash for a given list of dependencies."""
        cleaned = sorted([r.strip().lower() for r in requirements if r.strip()])
        if not cleaned:
            return "base_env"
        h = hashlib.md5()
        h.update("\n".join(cleaned).encode("utf-8"))
        return h.hexdigest()

    def get_venv_directory(self, requirements: list[str]) -> Path:
        """Returns the cached venv directory path for the given requirements."""
        reqs_hash = self.get_dependencies_hash(requirements)
        return self.venv_cache_dir / reqs_hash

    def setup_workspace(self, session_id: str, tool: GeneratedTool) -> Path:
        """Creates a workspace and writes the tool files (tool.py, requirements.txt)."""
        workspace = self.get_session_workspace(session_id)
        ensure_directory(workspace)

        # Write tool.py
        tool_file = workspace / "tool.py"
        tool_file.write_text(tool.code, encoding="utf-8")

        # Write requirements.txt
        req_file = workspace / "requirements.txt"
        req_content = "\n".join(tool.requirements)
        req_file.write_text(req_content, encoding="utf-8")

        return workspace

    def create_virtual_env(self, venv_dir: Path) -> Path:
        """Creates a virtual environment in the specified directory if it doesn't exist."""
        # If the path looks like a workspace directory (i.e. contains tool.py or requirements.txt),
        # create venv in .venv subdirectory to maintain backward compatibility
        target_dir = venv_dir
        if (venv_dir / "tool.py").exists() or (venv_dir / "requirements.txt").exists():
            target_dir = venv_dir / ".venv"

        if not target_dir.exists():
            logger.info("runtime_creating_venv_cache", path=str(target_dir))
            venv.create(target_dir, with_pip=True)
        return target_dir

    def install_dependencies(self, venv_dir: Path, requirements: list[str]) -> None:
        """Installs the list of dependencies into the cached virtual environment if needed."""
        cleaned = [r.strip() for r in requirements if r.strip()]
        if not cleaned:
            return

        # Determine python/pip executable based on OS
        if sys.platform == "win32":
            pip_executable = venv_dir / "Scripts" / "pip.exe"
            python_executable = venv_dir / "Scripts" / "python.exe"
        else:
            pip_executable = venv_dir / "bin" / "pip"
            python_executable = venv_dir / "bin" / "python"

        if not pip_executable.exists():
            raise FileNotFoundError(
                f"Virtual environment pip not found at {pip_executable}"
            )

        # Check if we have already installed these requirements by checking a sentinel file
        reqs_hash = self.get_dependencies_hash(requirements)
        sentinel_file = venv_dir / ".dependencies_installed"
        if sentinel_file.exists():
            try:
                if sentinel_file.read_text(encoding="utf-8").strip() == reqs_hash:
                    return
            except Exception:
                pass

        logger.info("runtime_installing_cached_dependencies", count=len(cleaned))

        # Write requirements temporarily inside the venv dir to run pip install
        temp_reqs = venv_dir / "temp_requirements.txt"
        temp_reqs.write_text("\n".join(cleaned), encoding="utf-8")

        try:
            # Upgrade pip first to avoid package installation bugs
            subprocess.run(
                [str(python_executable), "-m", "pip", "install", "--upgrade", "pip"],
                capture_output=True,
                check=True,
            )
            # Run pip install
            subprocess.run(
                [str(pip_executable), "install", "-r", str(temp_reqs)],
                capture_output=True,
                check=True,
            )
            # Write sentinel file with the requirements hash
            sentinel_file.write_text(reqs_hash, encoding="utf-8")
        finally:
            if temp_reqs.exists():
                temp_reqs.unlink()

    def execute_tool(
        self,
        session_id: str,
        input_data: str,
        requirements: list[str] | None = None,
        timeout: int | None = None,
    ) -> ExecutionResult:
        """Runs the tool wrapper script using the shared/cached virtual environment python interpreter."""
        workspace = self.get_session_workspace(session_id)

        # Determine venv dir based on requirements
        reqs = requirements or []
        venv_dir = self.get_venv_directory(reqs)
        self.create_virtual_env(venv_dir)
        self.install_dependencies(venv_dir, reqs)

        # Determine python executable based on OS
        if sys.platform == "win32":
            python_executable = venv_dir / "Scripts" / "python.exe"
        else:
            python_executable = venv_dir / "bin" / "python"

        if not python_executable.exists():
            raise FileNotFoundError(
                f"Python executable not found at {python_executable}"
            )

        wrapper_code = f"""
import json
import sys
import traceback
import tool

try:
    input_str = {input_data!r}
    # Try parsing input as JSON, then try ast.literal_eval, then fallback to raw string
    args = None
    try:
        args = json.loads(input_str)
    except Exception:
        try:
            import ast
            args = ast.literal_eval(input_str)
        except Exception:
            args = input_str

    if isinstance(args, dict):
        result = tool.run(**args)
    else:
        result = tool.run(args)
        
    print(json.dumps({{"status": "success", "output": result}}))
except Exception as e:
    tb_str = "".join(traceback.format_exception(type(e), e, e.__traceback__))
    sys.stderr.write(tb_str + "\\n")
    print(json.dumps({{"status": "error", "message": str(e), "traceback": tb_str}}), file=sys.stderr)
    sys.exit(1)
"""
        wrapper_file = workspace / "wrapper.py"
        wrapper_file.write_text(wrapper_code, encoding="utf-8")

        limit = timeout or self.timeout_seconds
        start_time = time.perf_counter()

        timed_out = False
        stdout = ""
        stderr = ""
        return_code = -1

        try:
            result = subprocess.run(
                [str(python_executable.resolve()), "wrapper.py"],
                capture_output=True,
                text=True,
                timeout=limit,
                cwd=str(workspace.resolve()),
            )
            stdout = result.stdout
            stderr = result.stderr
            return_code = result.returncode
        except subprocess.TimeoutExpired as e:
            timed_out = True
            stdout = (
                e.stdout.decode("utf-8", errors="replace")
                if isinstance(e.stdout, bytes)
                else (e.stdout or "")
            )
            stderr = (
                e.stderr.decode("utf-8", errors="replace")
                if isinstance(e.stderr, bytes)
                else (e.stderr or "Execution timed out")
            )
            return_code = -9

        runtime_ms = int((time.perf_counter() - start_time) * 1000)

        # Cleanup wrapper file
        if wrapper_file.exists():
            try:
                wrapper_file.unlink()
            except Exception:
                pass

        return ExecutionResult(
            stdout=stdout,
            stderr=stderr,
            return_code=return_code,
            runtime_ms=runtime_ms,
            timed_out=timed_out,
            workspace_path=workspace,
        )

    def cleanup_workspace(self, session_id: str) -> None:
        """Removes the entire session workspace directory."""
        workspace = self.get_session_workspace(session_id)
        if workspace.exists():
            remove_directory(workspace)
