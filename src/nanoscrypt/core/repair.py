import asyncio
import difflib
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


def classify_error(stderr: str, timed_out: bool, user_prompt: str = "") -> tuple[str, str]:
    """Classifies the execution or unit test failure and provides targeted repair guidance."""
    if timed_out:
        return "timeout", (
            "The execution timed out. Check for infinite loops, blocking network calls "
            "without timeouts, or excessive computation. Add timeout parameters to network "
            "requests (e.g., requests.get(url, timeout=10))."
        )

    if not stderr:
        return "unknown", "No error message captured. The process exited with a non-zero status code."

    err_lower = stderr.lower()
    if "syntaxerror" in stderr or "invalid syntax" in err_lower:
        return "syntax_error", (
            "The code has a Python syntax error. Check for missing colons, unmatched "
            "parentheses/brackets, invalid indentation, or incomplete string literals. "
            "Verify the entire file is syntactically valid Python 3.10."
        )
    elif "moduleboundnotfound" in err_lower or "modulenotfounderror" in stderr or "importerror" in stderr:
        return "import_error", (
            "One or more imports cannot be resolved. Check that: (1) all imported modules "
            "are correctly spelled, (2) third-party packages are listed in requirements, "
            "(3) local imports use the correct module name (e.g., 'import tool' not 'import tools'), "
            "(4) no Python 3.11+ stdlib modules are used without fallbacks."
        )
    elif "typeerror" in stderr:
        return "type_error", (
            "A function received arguments of the wrong type, or was called with the wrong "
            "number of arguments. Check that: (1) run() parameter types match what callers pass, "
            "(2) return values match annotations, (3) dict keys are accessed correctly, "
            "(4) None values are handled before method calls."
        )
    elif "zerodivisionerror" in stderr:
        return "zero_division", (
            "A division by zero occurred. Add guards: check divisors before dividing, "
            "return a sensible default (0, 0.0, or None) when the divisor is zero."
        )
    elif "assertionerror" in stderr:
        return "assertion_error", (
            "A test assertion failed. The tool produces output that does not match test "
            "expectations. Carefully read the test assertions and ensure run() returns "
            "values in the exact format, type, and structure the tests expect."
        )
    elif "attributeerror" in stderr:
        return "attribute_error", (
            "An object does not have an expected attribute or method. Check for: (1) None "
            "values being accessed with dot notation, (2) typos in attribute names, "
            "(3) wrong object types, (4) missing class methods."
        )
    elif "keyerror" in stderr:
        return "key_error", (
            "A dictionary key was accessed that does not exist. Use .get(key, default) "
            "instead of direct key access, or verify the dictionary structure matches "
            "expectations before accessing keys."
        )
    elif any(x in err_lower for x in ["connectionerror", "requests.exceptions", "urllib.error", "httperror", "socket.timeout", "dns"]):
        return "network_error", (
            "A network request failed. Ensure: (1) URLs are correct and accessible, "
            "(2) requests have timeout parameters, (3) connection errors are caught and "
            "handled gracefully with try/except, (4) the tool returns a sensible fallback "
            "value when the network is unavailable."
        )
    elif any(x in err_lower for x in ["unicodedecodeerror", "unicodeencodeerror", "charmap", "decode byte", "encode byte", "continuation byte", "start byte", "can't decode", "can't encode"]):
        binary_extensions = [".pdf", ".docx", ".xlsx", ".xls", ".png", ".jpg", ".jpeg", ".zip", ".tar.gz", "pdf", "docx", "xlsx"]
        prompt_lower = user_prompt.lower()
        if any(ext in prompt_lower for ext in binary_extensions) or "binary" in prompt_lower:
            return "binary_file_error", (
                "A binary decoding error occurred. The user prompt indicates processing of a binary file format "
                "(e.g. PDF, DOCX, XLSX, Images). DO NOT use `open(..., 'r')` or standard text reading. "
                "You MUST use a dedicated library like PyMuPDF (fitz) for PDF, python-docx for DOCX, "
                "openpyxl for XLSX, or Pillow for images. Update the code to use the correct library."
            )
        return "encoding_error", (
            "A text encoding error occurred. Add encoding='utf-8' to all open() calls "
            "that read or write text files. If the file is binary data, use mode='rb' or "
            "mode='wb'. For non-UTF-8 files, detect encoding with chardet or use "
            "errors='replace' / errors='ignore' as a fallback."
        )
    elif any(x in err_lower for x in ["filenotfounderror", "permissionerror", "isadirectoryerror"]):
        return "file_error", (
            "A file system error occurred. Validate file paths before use with "
            "pathlib.Path.exists(). Use pathlib for cross-platform path handling. "
            "Check that the file exists and the process has read/write permissions. "
            "Create parent directories with Path.mkdir(parents=True, exist_ok=True) "
            "if needed."
        )
    elif "valueerror" in stderr:
        return "value_error", (
            "A function received an argument with the right type but wrong value. "
            "Add input validation at the top of run(): check for empty strings, "
            "None values, out-of-range numbers, and invalid formats before processing. "
            "Use try/except around string parsing and format conversions."
        )
    elif "indexerror" in stderr:
        return "index_error", (
            "A list or sequence index is out of range. Add bounds checking before "
            "accessing elements by index. Use len() checks, guard clauses for empty "
            "sequences, and consider using safe access patterns like "
            "seq[i] if i < len(seq) else default."
        )
    elif any(x in err_lower for x in ["jsondecodeerror", "json.decoder"]):
        return "json_error", (
            "A JSON parsing error occurred. Validate that the input is valid JSON "
            "before parsing with json.loads(). Check for empty strings, truncated "
            "responses, or HTML error pages returned instead of JSON. Wrap "
            "json.loads() in try/except json.JSONDecodeError."
        )
    elif "runtimeerror" in stderr:
        return "runtime_error", (
            "A generic runtime error occurred. Review the full traceback for the specific "
            "cause. Common issues: event loop problems, recursion depth, or invalid state."
        )
    else:
        return "runtime_error", (
            "A runtime error occurred. Read the full traceback/stderr carefully, "
            "identify the root cause, and apply the appropriate fix."
        )


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
        
        # Ensure the virtual environment actually exists for these requirements
        # (The LLM may have changed requirements during repair, meaning a new venv is needed)
        self.runtime_manager.create_virtual_env(venv_dir)
        self.runtime_manager.install_dependencies(venv_dir, tool.requirements)

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
                timeout=30,  # Increased test timeout to 30s
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
        user_prompt: str = "",
    ) -> tuple[GeneratedTool | None, int]:
        """Tries to repair the tool code up to max_attempts times with exponential backoff and incremental memory."""
        log = logger.bind(component="repair_loop", tool_name=tool.name)

        current_tool = tool
        current_failure = failure_result
        attempt = 0

        max_attempts = settings.resilience.max_repair_attempts
        backoff_delay = settings.resilience.retry_delay_seconds

        # Incremental repair memory
        attempt_history = []

        while attempt < max_attempts:
            attempt += 1
            log.info("repair_attempt_started", attempt=attempt)

            # Apply backoff before retrying
            if attempt > 1 and settings.resilience.exponential_backoff:
                sleep_time = backoff_delay * (2 ** (attempt - 2))
                log.info("repair_backoff_sleep", sleep_seconds=sleep_time)
                await asyncio.sleep(sleep_time)

            # 1. Progressive Repair Strategy
            if attempt <= 2:
                strategy = "minimal_fix"
            elif attempt <= 4:
                strategy = "refactor"
            else:
                strategy = "rewrite"

            # 2. Targeted Error Classification
            error_classification, repair_guidance = classify_error(
                current_failure.stderr, current_failure.timed_out, user_prompt
            )

            # 3. Compile history of prior attempts
            if not attempt_history:
                prior_attempts_summary = "No prior attempts."
            else:
                summary_parts = []
                for h in attempt_history:
                    summary_parts.append(
                        f"Attempt {h['attempt']}:\n"
                        f"- Strategy used: {h['strategy']}\n"
                        f"- Error encountered: {h['error_classification']}\n"
                        f"- Diff of changes made:\n{h['diff']}\n"
                        f"- Error output details:\n{h['stderr']}"
                    )
                prior_attempts_summary = "\n\n".join(summary_parts)

            # 4. Format requirements and manifest
            requirements_str = ", ".join(current_tool.requirements) if current_tool.requirements else "None"
            manifest_str = (
                current_tool.manifest.model_dump_json(indent=2)
                if hasattr(current_tool.manifest, "model_dump_json")
                else str(current_tool.manifest)
            )

            # 5. Build prompt
            prompt = TOOL_REPAIR_USER_TEMPLATE.format(
                tool_name=current_tool.name,
                tool_purpose=tool_purpose,
                user_prompt=user_prompt,
                strategy=strategy,
                attempt_number=attempt,
                max_attempts=max_attempts,
                error_classification=error_classification,
                repair_guidance=repair_guidance,
                current_code=current_tool.code,
                tests_code=current_tool.tests,
                manifest=manifest_str,
                requirements=requirements_str,
                return_code=current_failure.return_code,
                stdout=current_failure.stdout,
                error_msg=current_failure.stderr or "No error output captured",
                prior_attempts_summary=prior_attempts_summary,
            )

            try:
                patched_tool = await self.llm.generate_structured(
                    prompt=prompt,
                    response_model=GeneratedTool,
                    system_prompt=TOOL_REPAIR_SYSTEM_PROMPT,
                )

                # Generate code change diff for memory tracking
                old_lines = current_tool.code.splitlines(keepends=True)
                new_lines = patched_tool.code.splitlines(keepends=True)
                diff = "".join(
                    difflib.unified_diff(
                        old_lines, new_lines, fromfile="before_patch", tofile="after_patch"
                    )
                )

                # Post-process: auto-fix common LLM code issues
                from nanoscrypt.core.postprocessor import CodePostProcessor
                post_processor = CodePostProcessor()
                patched_tool = post_processor.process(patched_tool)

                # 6. Post-Repair Validation Gate (validate BEFORE running tests)
                val_res = self.validator.validate(patched_tool)
                if not val_res.is_valid:
                    log.warning("repair_validation_failed", attempt=attempt)
                    validation_errors = "\n".join([iss.message for iss in val_res.issues])

                    # Record this failed attempt in history
                    attempt_history.append({
                        "attempt": attempt,
                        "strategy": strategy,
                        "error_classification": "validation_failed",
                        "diff": diff or "No code changes.",
                        "stderr": f"Static validation failed:\n{validation_errors}",
                    })

                    current_failure = ExecutionResult(
                        stdout="",
                        stderr=f"Static validation failed:\n{validation_errors}",
                        return_code=-1,
                        runtime_ms=0,
                        timed_out=False,
                        workspace_path=failure_result.workspace_path,
                    )
                    current_tool = patched_tool
                    continue

                if val_res.formatted_code:
                    patched_tool.code = val_res.formatted_code

                # 7. Run tests on the patched tool
                self.runtime_manager.setup_workspace(session_id, patched_tool)
                test_res = self.run_tests_in_sandbox(session_id, patched_tool)

                if test_res.return_code == 0:
                    log.info("repair_succeeded", attempt=attempt)
                    return patched_tool, attempt
                else:
                    log.warning("repair_tests_failed", attempt=attempt)
                    attempt_history.append({
                        "attempt": attempt,
                        "strategy": strategy,
                        "error_classification": error_classification,
                        "diff": diff or "No code changes.",
                        "stderr": test_res.stderr or f"Test exited with code {test_res.return_code}",
                    })
                    current_failure = test_res
                    current_tool = patched_tool

            except Exception as e:
                log.error("repair_attempt_exception", attempt=attempt, error=str(e))
                attempt_history.append({
                    "attempt": attempt,
                    "strategy": strategy,
                    "error_classification": "exception",
                    "diff": "Exception occurred during repair execution.",
                    "stderr": f"Repair loop logic error: {e!s}",
                })
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
