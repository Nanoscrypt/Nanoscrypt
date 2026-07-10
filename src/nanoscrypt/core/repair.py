import asyncio
import subprocess
import sys

import structlog

from nanoscrypt.config.settings import settings
from nanoscrypt.core.runtime import ExecutionResult, RuntimeManager
from nanoscrypt.core.validator import ToolValidator
from nanoscrypt.llm.base import LLMProvider
from nanoscrypt.llm.prompts.repair import (
    TOOL_REPAIR_SYSTEM_PROMPT,
    TOOL_REPAIR_USER_TEMPLATE,
)
from nanoscrypt.models.tool import GeneratedTool

logger = structlog.get_logger()


class RepairLoop:
    """Manages test executions and self-repair iteration loops for malfunctioning tools."""

    def __init__(
        self,
        llm: LLMProvider,
        validator: ToolValidator,
        runtime_manager: RuntimeManager,
        max_attempts: int = 5,
    ):
        self.llm = llm
        self.validator = validator
        self.runtime_manager = runtime_manager
        self.max_attempts = max_attempts

    def run_tests_in_sandbox(
        self, session_id: str, tool: GeneratedTool
    ) -> ExecutionResult:
        """Executes the tool's tests.py inside the workspace sandbox using pytest."""
        workspace = self.runtime_manager.get_session_workspace(session_id)
        venv_dir = self.runtime_manager.get_venv_directory(tool.requirements)

        # Write tests.py file to sandbox
        (workspace / "tests.py").write_text(tool.tests, encoding="utf-8")

        # Determine python/pytest executable path
        if sys.platform == "win32":
            pytest_bin = venv_dir / "Scripts" / "pytest.exe"
        else:
            pytest_bin = venv_dir / "bin" / "pytest"

        if not pytest_bin.exists():
            # If pytest is not installed, run standard python -m unittest on tests.py
            if sys.platform == "win32":
                python_bin = venv_dir / "Scripts" / "python.exe"
            else:
                python_bin = venv_dir / "bin" / "python"
            cmd = [str(python_bin), "-m", "unittest", "tests.py"]
        else:
            cmd = [str(pytest_bin), "tests.py"]

        timed_out = False
        stdout = ""
        stderr = ""
        return_code = -1

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,  # short timeout for tests
                cwd=str(workspace),
            )
            stdout = result.stdout
            stderr = result.stderr
            return_code = result.returncode
        except subprocess.TimeoutExpired as e:
            timed_out = True
            stdout = e.stdout or ""
            stderr = e.stderr or "Tests execution timed out"
            return_code = -9

        return ExecutionResult(
            stdout=stdout,
            stderr=stderr,
            return_code=return_code,
            runtime_ms=0,
            timed_out=timed_out,
            workspace_path=workspace,
        )

    async def repair_tool(
        self,
        session_id: str,
        tool: GeneratedTool,
        failure_result: ExecutionResult,
        tool_purpose: str,
    ) -> tuple[GeneratedTool | None, int]:
        """Tries to repair the tool code up to max_attempts times with exponential backoff."""
        log = logger.bind(component="repair_loop", tool_name=tool.name)

        current_tool = tool
        current_failure = failure_result
        attempt = 0

        max_attempts = settings.resilience.max_repair_attempts
        backoff_delay = settings.resilience.retry_delay_seconds

        while attempt < max_attempts:
            attempt += 1
            log.info("repair_attempt_started", attempt=attempt)

            # Apply backoff before retrying
            if attempt > 1 and settings.resilience.exponential_backoff:
                sleep_time = backoff_delay * (2 ** (attempt - 2))
                log.info("repair_backoff_sleep", sleep_seconds=sleep_time)
                await asyncio.sleep(sleep_time)

            # Build repair request prompt
            prompt = TOOL_REPAIR_USER_TEMPLATE.format(
                tool_name=current_tool.name,
                tool_purpose=tool_purpose,
                current_code=current_tool.code,
                return_code=current_failure.return_code,
                stdout=current_failure.stdout,
                error_msg=current_failure.stderr or "No error output captured",
            )

            try:
                patched_tool = await self.llm.generate_structured(
                    prompt=prompt,
                    response_model=GeneratedTool,
                    system_prompt=TOOL_REPAIR_SYSTEM_PROMPT,
                )

                # Validate the patched code
                val_res = self.validator.validate(patched_tool)
                if not val_res.is_valid:
                    log.warning("repair_validation_failed", attempt=attempt)
                    # Use validation issues as new diagnostics for next iteration
                    current_failure = ExecutionResult(
                        stdout="",
                        stderr="\n".join([iss.message for iss in val_res.issues]),
                        return_code=-1,
                        runtime_ms=0,
                        timed_out=False,
                        workspace_path=failure_result.workspace_path,
                    )
                    current_tool = patched_tool
                    continue

                if val_res.formatted_code:
                    patched_tool.code = val_res.formatted_code

                # Run tests on the patched tool
                # Re-setup the sandbox with new tool code
                self.runtime_manager.setup_workspace(session_id, patched_tool)
                test_res = self.run_tests_in_sandbox(session_id, patched_tool)

                if test_res.return_code == 0:
                    log.info("repair_succeeded", attempt=attempt)
                    return patched_tool, attempt
                else:
                    log.warning("repair_tests_failed", attempt=attempt)
                    current_failure = test_res
                    current_tool = patched_tool

            except Exception as e:
                log.error("repair_attempt_exception", attempt=attempt, error=str(e))
                # Set dummy failure result to report
                current_failure = ExecutionResult(
                    stdout="",
                    stderr=f"Repair loop logic error: {e!s}",
                    return_code=-1,
                    runtime_ms=0,
                    timed_out=False,
                    workspace_path=failure_result.workspace_path,
                )

        log.error("repair_failed_max_attempts_exceeded")
        return None, attempt
