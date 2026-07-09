import ast
import json
import subprocess
import tempfile
from pathlib import Path
from dataclasses import dataclass, field
import structlog
from nanoscrypt.models.tool import GeneratedTool

logger = structlog.get_logger()

@dataclass
class ValidationIssue:
    stage: str
    severity: str  # "error" or "warning"
    message: str
    line: int | None = None

@dataclass
class ValidationResult:
    is_valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    formatted_code: str | None = None

class SecurityASTVisitor(ast.NodeVisitor):
    """AST visitor that checks for dangerous calls, imports, and attributes."""
    
    BLOCKED_IMPORTS = {
        'os', 'sys', 'subprocess', 'shutil', 'ctypes', 
        'importlib', 'socket', 'signal', 'multiprocessing',
        'threading', 'pickle', 'shelve', 'code', 'codeop'
    }
    
    BLOCKED_BUILTINS = {
        'exec', 'eval', 'compile', '__import__', 
        'globals', 'locals', 'vars', 'dir',
        'breakpoint', 'exit', 'quit'
    }
    
    BLOCKED_ATTRS = {
        '__subclasses__', '__bases__', '__class__',
        '__globals__', '__code__', '__builtins__'
    }

    def __init__(self) -> None:
        self.issues: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root_module = alias.name.split('.')[0]
            if root_module in self.BLOCKED_IMPORTS:
                self.issues.append(f"Line {node.lineno}: Blocked import '{alias.name}'")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            root_module = node.module.split('.')[0]
            if root_module in self.BLOCKED_IMPORTS:
                self.issues.append(f"Line {node.lineno}: Blocked import from '{node.module}'")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            if node.func.id in self.BLOCKED_BUILTINS:
                self.issues.append(f"Line {node.lineno}: Blocked builtin call '{node.func.id}'")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in self.BLOCKED_ATTRS:
            self.issues.append(f"Line {node.lineno}: Blocked attribute access '.{node.attr}'")
        self.generic_visit(node)

class ResourceAccessScanner(ast.NodeVisitor):
    """AST visitor to detect file access and network requests in tool code."""
    def __init__(self) -> None:
        self.has_file_access = False
        self.has_network_access = False
        
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split('.')[0]
            if root in {"requests", "urllib", "httpx", "aiohttp", "socket", "http", "ftplib", "smtplib"}:
                self.has_network_access = True
            if root in {"csv", "json", "pandas", "openpyxl", "sqlite3"}:
                self.has_file_access = True
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            root = node.module.split('.')[0]
            if root in {"requests", "urllib", "httpx", "aiohttp", "socket", "http", "ftplib", "smtplib"}:
                self.has_network_access = True
            if root in {"csv", "json", "pandas", "openpyxl", "sqlite3"}:
                self.has_file_access = True
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            if node.func.id == "open":
                self.has_file_access = True
        elif isinstance(node.func, ast.Attribute):
            if node.func.attr in {"read_text", "read_bytes", "write_text", "write_bytes", "read_csv", "to_csv"}:
                self.has_file_access = True
        self.generic_visit(node)

class ToolValidator:
    """Performs multi-stage validation checks on dynamically generated tools."""

    def validate_syntax(self, code: str) -> list[ValidationIssue]:
        issues = []
        try:
            compile(code, "<string>", "exec")
        except SyntaxError as e:
            issues.append(ValidationIssue(
                stage="syntax",
                severity="error",
                message=f"Syntax error: {e.msg}",
                line=e.lineno
            ))
        return issues

    def validate_security(self, code: str) -> list[ValidationIssue]:
        issues = []
        try:
            tree = ast.parse(code)
            visitor = SecurityASTVisitor()
            visitor.visit(tree)
            for iss in visitor.issues:
                issues.append(ValidationIssue(
                    stage="security",
                    severity="error",
                    message=iss
                ))
        except Exception as e:
            issues.append(ValidationIssue(
                stage="security",
                severity="error",
                message=f"AST parsing failure during security checks: {str(e)}"
            ))
        return issues

    def scan_resource_access(self, code: str) -> dict[str, bool]:
        """Statically scans tool code for file system or network access indicators."""
        try:
            tree = ast.parse(code)
            scanner = ResourceAccessScanner()
            scanner.visit(tree)
            return {
                "file_access": scanner.has_file_access,
                "network_access": scanner.has_network_access
            }
        except Exception:
            return {"file_access": False, "network_access": False}

    def validate_entry_point(self, code: str) -> list[ValidationIssue]:
        issues = []
        try:
            tree = ast.parse(code)
            has_run = False
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run":
                    has_run = True
                    # Check type hints
                    if not node.returns:
                        issues.append(ValidationIssue(
                            stage="entry_point",
                            severity="warning",
                            message="Entry function 'run(...)' is missing a return type annotation."
                        ))
                    if not node.args.args:
                        issues.append(ValidationIssue(
                            stage="entry_point",
                            severity="warning",
                            message="Entry function 'run(...)' should accept parameters."
                        ))
            if not has_run:
                issues.append(ValidationIssue(
                    stage="entry_point",
                    severity="error",
                    message="Tool missing mandatory 'run(...)' entry point function."
                ))
        except Exception:
            pass  # Handled by syntax validation
        return issues

    def run_ruff_formatting_and_lint(self, code: str) -> tuple[str, list[ValidationIssue]]:
        issues = []
        formatted_code = code

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "tool_temp.py"
            file_path.write_text(code, encoding="utf-8")

            # Run ruff format
            try:
                subprocess.run(
                    ["ruff", "format", str(file_path)],
                    capture_output=True,
                    check=False
                )
                formatted_code = file_path.read_text(encoding="utf-8")
            except Exception as e:
                issues.append(ValidationIssue(
                    stage="formatting",
                    severity="warning",
                    message=f"Ruff format run failed: {str(e)}"
                ))

            # Run ruff check
            try:
                result = subprocess.run(
                    ["ruff", "check", "--output-format=json", str(file_path)],
                    capture_output=True,
                    text=True,
                    check=False
                )
                if result.stdout:
                    try:
                        ruff_diagnostics = json.loads(result.stdout)
                        for d in ruff_diagnostics:
                            issues.append(ValidationIssue(
                                stage="lint",
                                severity="warning",
                                message=f"[{d.get('code')}] {d.get('message')}",
                                line=d.get('location', {}).get('row')
                            ))
                    except Exception:
                        pass
            except Exception as e:
                issues.append(ValidationIssue(
                    stage="lint",
                    severity="warning",
                    message=f"Ruff check execution failed: {str(e)}"
                ))

        return formatted_code, issues

    def validate(self, tool: GeneratedTool) -> ValidationResult:
        log = logger.bind(component="validator", tool_name=tool.name)
        log.debug("validator_checking_started")

        all_issues = []

        # 1. Syntax check
        syntax_issues = self.validate_syntax(tool.code)
        all_issues.extend(syntax_issues)
        if any(iss.severity == "error" for iss in syntax_issues):
            return ValidationResult(is_valid=False, issues=all_issues)

        # 2. Security Check
        security_issues = self.validate_security(tool.code)
        all_issues.extend(security_issues)

        # 3. Entry point Check
        entry_issues = self.validate_entry_point(tool.code)
        all_issues.extend(entry_issues)

        # 4. Ruff Format + Lint
        formatted, lint_issues = self.run_ruff_formatting_and_lint(tool.code)
        all_issues.extend(lint_issues)

        # If any validation issue is of severity "error", validation fails
        is_valid = not any(iss.severity == "error" for iss in all_issues)
        
        log.info("validator_checking_completed", is_valid=is_valid, issues_count=len(all_issues))
        return ValidationResult(
            is_valid=is_valid,
            issues=all_issues,
            formatted_code=formatted
        )
