import os
import sys
import venv
import subprocess
from pathlib import Path
import time
from dataclasses import dataclass
import structlog
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
    """Manages isolated workspaces and execution environments for running generated tools."""

    def __init__(self, workspace_root: Path | str, timeout_seconds: int = 30):
        self.workspace_root = Path(workspace_root)
        self.timeout_seconds = timeout_seconds
        ensure_directory(self.workspace_root)

    def get_session_workspace(self, session_id: str) -> Path:
        """Returns the isolated path for a specific session's workspace."""
        return self.workspace_root / session_id

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

    def create_virtual_env(self, workspace_path: Path) -> Path:
        """Creates a local virtual environment in the workspace."""
        venv_dir = workspace_path / ".venv"
        if not venv_dir.exists():
            venv.create(venv_dir, with_pip=True)
        return venv_dir

    def install_dependencies(self, workspace_path: Path) -> None:
        """Installs the dependencies listed in requirements.txt into the virtual environment."""
        venv_dir = workspace_path / ".venv"
        req_file = workspace_path / "requirements.txt"

        # If requirements file is empty or missing, skip installation
        if not req_file.exists() or not req_file.read_text(encoding="utf-8").strip():
            return

        # Determine python/pip executable based on OS
        if sys.platform == "win32":
            pip_executable = venv_dir / "Scripts" / "pip.exe"
        else:
            pip_executable = venv_dir / "bin" / "pip"

        if not pip_executable.exists():
            raise FileNotFoundError(f"Virtual environment pip not found at {pip_executable}")

        # Run pip install in sandbox
        subprocess.run(
            [str(pip_executable), "install", "-r", str(req_file)],
            capture_output=True,
            check=True
        )

    def execute_tool(
        self, 
        session_id: str, 
        input_data: str,
        timeout: int | None = None
    ) -> ExecutionResult:
        """Runs the tool in the isolated environment passing input_data via script execution wrapper."""
        workspace = self.get_session_workspace(session_id)
        venv_dir = workspace / ".venv"
        
        # Determine python executable based on OS
        if sys.platform == "win32":
            python_executable = venv_dir / "Scripts" / "python.exe"
        else:
            python_executable = venv_dir / "bin" / "python"

        if not python_executable.exists():
            raise FileNotFoundError(f"Python executable not found at {python_executable}")

        # We execute a small wrapper script to load tool.run and pass input_data
        wrapper_code = f"""
import json
import sys
import tool

try:
    input_str = {repr(input_data)}
    # Try parsing input as JSON if possible, otherwise pass as raw string
    try:
        args = json.loads(input_str)
    except Exception:
        args = input_str

    if isinstance(args, dict):
        result = tool.run(**args)
    else:
        result = tool.run(args)
        
    print(json.dumps({{"status": "success", "output": result}}))
except Exception as e:
    print(json.dumps({{"status": "error", "message": str(e)}}), file=sys.stderr)
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
                cwd=str(workspace.resolve())
            )
            stdout = result.stdout
            stderr = result.stderr
            return_code = result.returncode
        except subprocess.TimeoutExpired as e:
            timed_out = True
            stdout = e.stdout.decode('utf-8', errors='replace') if isinstance(e.stdout, bytes) else (e.stdout or "")
            stderr = e.stderr.decode('utf-8', errors='replace') if isinstance(e.stderr, bytes) else (e.stderr or "Execution timed out")
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
            workspace_path=workspace
        )

    def cleanup_workspace(self, session_id: str) -> None:
        """Removes the entire session workspace directory."""
        workspace = self.get_session_workspace(session_id)
        if workspace.exists():
            remove_directory(workspace)
