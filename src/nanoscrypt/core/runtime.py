import hashlib
import os
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
        return (self.workspace_root / session_id).resolve()

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

    def setup_application_workspace(self, session_id: str, app_manifest) -> Path:
        """Scaffolds a multi-file project workspace preserving directory structure."""
        workspace = self.get_session_workspace(session_id)
        ensure_directory(workspace)

        # Write all files in the manifest dictionary
        for rel_path, content in app_manifest.files.items():
            dest = (workspace / rel_path).resolve()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")

        # Ensure requirements.txt or package.json exists if dependencies were declared
        if getattr(app_manifest, "language", "python") == "python":
            req_file = workspace / "requirements.txt"
            if not req_file.exists() and app_manifest.dependencies:
                req_file.write_text("\n".join(app_manifest.dependencies), encoding="utf-8")
        elif getattr(app_manifest, "language", "") in ("javascript", "typescript", "node"):
            pkg_file = workspace / "package.json"
            if not pkg_file.exists():
                import json
                deps_dict = {dep: "latest" for dep in app_manifest.dependencies}
                pkg_data = {
                    "name": app_manifest.name or "nanoscrypt-app",
                    "version": "1.0.0",
                    "main": app_manifest.entry_point or "server.js",
                    "dependencies": deps_dict
                }
                pkg_file.write_text(json.dumps(pkg_data, indent=2), encoding="utf-8")

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
            res = subprocess.run(
                [str(pip_executable), "install", "-r", str(temp_reqs)],
                capture_output=True,
                text=True,
            )
            if res.returncode != 0:
                logger.warning(
                    "pip_install_failed_continuing_offline",
                    stderr=res.stderr,
                    stdout=res.stdout,
                )
                # If network fails or pip install fails, check if standard modules exist or continue gracefully
                print(f"\n[Warning] Pip install offline/failed for {cleaned}. Attempting tool execution with available environment packages...")
            else:
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

        # Check if venv is disabled in settings
        if not getattr(settings.runtime, "use_venv", True):
            python_executable = Path(sys.executable)
        else:
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
import inspect
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
        # Introspect run() signature and fill missing params with defaults
        try:
            sig = inspect.signature(tool.run)
            for param_name, param in sig.parameters.items():
                if param_name not in args and param.default is not inspect.Parameter.empty:
                    args[param_name] = param.default
        except Exception:
            pass
        result = tool.run(**args)
    elif args is None or args == '' or args == '{{}}':
        # No args provided - call run() with no arguments (relies on defaults)
        result = tool.run()
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

        # Determine execution command list with absolute wrapper path
        wrapper_path = (workspace / "wrapper.py").resolve()
        cmd = [str(python_executable.resolve()), str(wrapper_path)]
        if settings.runtime.capsem_enabled:
            import shutil
            if shutil.which("capsem"):
                cmd = ["capsem"] + cmd
                logger.info("runtime_executing_via_capsem_sandbox", command=cmd)
            else:
                logger.warning("runtime_capsem_enabled_but_binary_not_found_falling_back")

        project_root = Path(".").resolve()
        env = dict(os.environ)
        env["PROJECT_ROOT"] = str(project_root)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(workspace.resolve()), env.get("PYTHONPATH", "")]
        )

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=limit,
                cwd=str(project_root),
                env=env,
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

    def execute_application(
        self,
        session_id: str,
        app_manifest,
        timeout: int | None = None,
    ) -> ExecutionResult:
        """Executes a multi-file polyglot application or starts it as a supervised daemon."""
        workspace = self.setup_application_workspace(session_id, app_manifest)
        language = getattr(app_manifest, "language", "python").lower()

        # Handle Python
        if language == "python":
            venv_dir = self.get_venv_directory(app_manifest.dependencies)
            self.create_virtual_env(venv_dir)
            self.install_dependencies(venv_dir, app_manifest.dependencies)

            if sys.platform == "win32":
                python_executable = venv_dir / "Scripts" / "python.exe"
            else:
                python_executable = venv_dir / "bin" / "python"

            cmd = [str(python_executable.resolve()), app_manifest.entry_point]

        # Handle Node.js / JavaScript / TypeScript
        elif language in ("javascript", "typescript", "node"):
            # If npm dependencies exist, run npm install
            if app_manifest.dependencies:
                subprocess.run(["npm", "install"], cwd=str(workspace), capture_output=True)
            cmd = ["node", app_manifest.entry_point]

        # Handle Go
        elif language == "go":
            cmd = ["go", "run", app_manifest.entry_point]

        # Handle Rust
        elif language == "rust":
            cmd = ["cargo", "run"]

        else:
            raise ValueError(f"Unsupported language driver: {language}")

        # If daemon / long-running web application
        if getattr(app_manifest, "is_daemon", False):
            import socket
            import time

            logger.info("runtime_starting_daemon_application", name=app_manifest.name, port=app_manifest.port)
            proc = subprocess.Popen(
                cmd,
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            # Wait briefly to confirm port is listening
            port = app_manifest.port or 8080
            time.sleep(1.5)

            # Check if process died immediately
            if proc.poll() is not None:
                stdout, stderr = proc.communicate()
                return ExecutionResult(
                    stdout=stdout,
                    stderr=stderr,
                    return_code=proc.returncode,
                    runtime_ms=1500,
                    timed_out=False,
                    workspace_path=workspace,
                )

            return ExecutionResult(
                stdout=f"Daemon application '{app_manifest.name}' successfully launched on port {port}. PID: {proc.pid}",
                stderr="",
                return_code=0,
                runtime_ms=1500,
                timed_out=False,
                workspace_path=workspace,
            )

        # Standard execution for non-daemon applications
        limit = timeout or self.timeout_seconds
        start_time = time.perf_counter()
        res = subprocess.run(cmd, cwd=str(workspace), capture_output=True, text=True, timeout=limit)
        runtime_ms = int((time.perf_counter() - start_time) * 1000)

        return ExecutionResult(
            stdout=res.stdout,
            stderr=res.stderr,
            return_code=res.returncode,
            runtime_ms=runtime_ms,
            timed_out=False,
            workspace_path=workspace,
        )

    def cleanup_workspace(self, session_id: str) -> None:
        """Removes the entire session workspace directory."""
        workspace = self.get_session_workspace(session_id)
        if workspace == Path(self.workspace_root).resolve():
            return
        if workspace.exists():
            remove_directory(workspace)

