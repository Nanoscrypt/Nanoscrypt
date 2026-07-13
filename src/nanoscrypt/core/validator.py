import ast
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import structlog

from nanoscrypt.models.tool import GeneratedTool, ToolManifest

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
        "os",
        "sys",
        "subprocess",
        "shutil",
        "ctypes",
        "importlib",
        "socket",
        "signal",
        "multiprocessing",
        "threading",
        "pickle",
        "shelve",
        "code",
        "codeop",
    }

    BLOCKED_BUILTINS = {
        "exec",
        "eval",
        "compile",
        "__import__",
        "globals",
        "locals",
        "vars",
        "dir",
        "breakpoint",
        "exit",
        "quit",
    }

    BLOCKED_ATTRS = {
        "__subclasses__",
        "__bases__",
        "__class__",
        "__globals__",
        "__code__",
        "__builtins__",
    }

    def __init__(self) -> None:
        self.issues: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root_module = alias.name.split(".")[0]
            if root_module in self.BLOCKED_IMPORTS:
                self.issues.append(f"Line {node.lineno}: Blocked import '{alias.name}'")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            root_module = node.module.split(".")[0]
            if root_module in self.BLOCKED_IMPORTS:
                self.issues.append(
                    f"Line {node.lineno}: Blocked import from '{node.module}'"
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            if node.func.id in self.BLOCKED_BUILTINS:
                self.issues.append(
                    f"Line {node.lineno}: Blocked builtin call '{node.func.id}'"
                )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in self.BLOCKED_ATTRS:
            self.issues.append(
                f"Line {node.lineno}: Blocked attribute access '.{node.attr}'"
            )
        self.generic_visit(node)


class ResourceAccessScanner(ast.NodeVisitor):
    """AST visitor to detect file access and network requests in tool code."""

    def __init__(self) -> None:
        self.has_file_access = False
        self.has_network_access = False

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in {
                "requests",
                "urllib",
                "httpx",
                "aiohttp",
                "socket",
                "http",
                "ftplib",
                "smtplib",
            }:
                self.has_network_access = True
            if root in {"csv", "json", "pandas", "openpyxl", "sqlite3"}:
                self.has_file_access = True
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            root = node.module.split(".")[0]
            if root in {
                "requests",
                "urllib",
                "httpx",
                "aiohttp",
                "socket",
                "http",
                "ftplib",
                "smtplib",
            }:
                self.has_network_access = True
            if root in {"csv", "json", "pandas", "openpyxl", "sqlite3"}:
                self.has_file_access = True
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            if node.func.id == "open":
                self.has_file_access = True
        elif isinstance(node.func, ast.Attribute):
            if node.func.attr in {
                "read_text",
                "read_bytes",
                "write_text",
                "write_bytes",
                "read_csv",
                "to_csv",
            }:
                self.has_file_access = True
        self.generic_visit(node)


def _normalize_package_name(name: str) -> str:
    """Normalize a package name by replacing hyphens and underscores with a
    canonical form (lowercase, hyphens -> underscores) for comparison."""
    return re.sub(r"[-_]+", "_", name).lower()


def _is_dependency_satisfied(mod_name: str, norm_reqs: set[str], llm=None) -> bool:
    """Checks if an import module name is satisfied by the list of normalized requirements."""
    norm_mod = _normalize_package_name(mod_name)
    if norm_mod in norm_reqs:
        return True
    
    # Check mappings dynamically using LLM knowledge if available
    if llm:
        import asyncio
        import concurrent.futures
        
        async def _check_via_llm():
            prompt = (
                f"You are a Python dependency checking assistant.\n"
                f"Question: Does any pip package in the list {list(norm_reqs)} satisfy or provide "
                f"the python import module '{mod_name}' (for example, the package 'PyMuPDF' provides 'fitz', 'Pillow' provides 'PIL')?\n"
                f"Respond ONLY with 'yes' or 'no' (no markdown, no punctuation)."
            )
            try:
                res = await llm.generate(prompt=prompt, temperature=0.0)
                return res.strip().lower() == "yes"
            except Exception:
                return False
                
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    return executor.submit(asyncio.run, _check_via_llm()).result()
            else:
                return asyncio.run(_check_via_llm())
        except Exception:
            pass
            
    return False


def _get_stdlib_modules() -> frozenset[str]:
    """Return the set of stdlib module names. Uses sys.stdlib_module_names
    available in Python 3.10+."""
    return frozenset(sys.stdlib_module_names)


def _extract_imported_root_modules(tree: ast.Module) -> list[tuple[str, int]]:
    """Walk an AST and return a list of (root_module_name, lineno) for every
    import statement found at any level."""
    results: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                results.append((root, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root = node.module.split(".")[0]
                results.append((root, node.lineno))
    return results


def _find_run_function(tree: ast.Module) -> Optional[ast.FunctionDef]:
    """Return the top-level ``run()`` FunctionDef/AsyncFunctionDef node, or
    None if it doesn't exist."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run":
            return node
    return None


def _get_return_annotation_name(node: ast.FunctionDef) -> Optional[str]:
    """Try to extract a simple string name from the return annotation of a
    function node (e.g. 'dict', 'str').  Returns None when the annotation is
    absent or too complex to resolve to a simple name."""
    if node.returns is None:
        return None
    ann = node.returns
    if isinstance(ann, ast.Name):
        return ann.id
    if isinstance(ann, ast.Constant) and isinstance(ann.value, str):
        return ann.value
    return None


def _collect_names_and_attrs(tree: ast.AST) -> set[str]:
    """Collect all Name.id and Attribute.attr strings referenced anywhere
    inside *tree* (recursively)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


class ToolValidator:
    """Performs multi-stage validation checks on dynamically generated tools."""

    def __init__(self, llm=None):
        self.llm = llm

    # ------------------------------------------------------------------
    # Stage 1: Syntax
    # ------------------------------------------------------------------

    def validate_syntax(self, code: str) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        try:
            compile(code, "<string>", "exec")
        except SyntaxError as e:
            issues.append(
                ValidationIssue(
                    stage="syntax",
                    severity="error",
                    message=f"Syntax error: {e.msg}",
                    line=e.lineno,
                )
            )
        return issues

    # ------------------------------------------------------------------
    # Stage 3: Security
    # ------------------------------------------------------------------

    def validate_security(self, code: str) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        try:
            tree = ast.parse(code)
            visitor = SecurityASTVisitor()
            visitor.visit(tree)
            for iss in visitor.issues:
                issues.append(
                    ValidationIssue(stage="security", severity="error", message=iss)
                )
        except Exception as e:
            issues.append(
                ValidationIssue(
                    stage="security",
                    severity="error",
                    message=f"AST parsing failure during security checks: {e!s}",
                )
            )
        return issues

    # ------------------------------------------------------------------
    # Resource access scanning (utility – not a pass/fail stage)
    # ------------------------------------------------------------------

    def scan_resource_access(self, code: str) -> dict[str, bool]:
        """Statically scans tool code for file system or network access indicators."""
        try:
            tree = ast.parse(code)
            scanner = ResourceAccessScanner()
            scanner.visit(tree)
            return {
                "file_access": scanner.has_file_access,
                "network_access": scanner.has_network_access,
            }
        except Exception:
            return {"file_access": False, "network_access": False}

    # ------------------------------------------------------------------
    # Stage 4: Entry point
    # ------------------------------------------------------------------

    def validate_entry_point(self, code: str) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        try:
            tree = ast.parse(code)
            has_run = False
            for node in tree.body:
                if (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == "run"
                ):
                    has_run = True
                    # Check type hints
                    if not node.returns:
                        issues.append(
                            ValidationIssue(
                                stage="entry_point",
                                severity="warning",
                                message="Entry function 'run(...)' is missing a return type annotation.",
                            )
                        )
                    if not node.args.args:
                        issues.append(
                            ValidationIssue(
                                stage="entry_point",
                                severity="warning",
                                message="Entry function 'run(...)' should accept parameters.",
                            )
                        )
            if not has_run:
                issues.append(
                    ValidationIssue(
                        stage="entry_point",
                        severity="error",
                        message="Tool missing mandatory 'run(...)' entry point function.",
                    )
                )
        except Exception:
            pass  # Handled by syntax validation
        return issues

    # ------------------------------------------------------------------
    # Stage 5 (NEW): Import availability
    # ------------------------------------------------------------------

    def validate_imports(
        self, code: str, requirements: list[str]
    ) -> list[ValidationIssue]:
        """Verify every imported module is either stdlib or listed in
        *requirements* (with normalized name comparison)."""
        issues: list[ValidationIssue] = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues  # syntax stage will catch this

        stdlib = _get_stdlib_modules()
        # Build a set of normalized requirement root package names.
        # Requirements entries may look like "requests>=2.28" – strip version
        # specifiers to get the bare package name.
        norm_reqs: set[str] = set()
        for req in requirements:
            # Strip extras, version specifiers, etc.
            bare = re.split(r"[>=<!;\[\]]", req, maxsplit=1)[0].strip()
            if bare:
                norm_reqs.add(_normalize_package_name(bare))

        imported = _extract_imported_root_modules(tree)
        for mod_name, lineno in imported:
            if mod_name in stdlib:
                continue
            if _is_dependency_satisfied(mod_name, norm_reqs, self.llm):
                continue
            # Check common aliases: e.g. ``import cv2`` -> package ``opencv-python``
            # We simply flag unknown modules as errors.
            issues.append(
                ValidationIssue(
                    stage="imports",
                    severity="error",
                    message=(
                        f"Import '{mod_name}' is neither a stdlib module nor "
                        f"listed in requirements."
                    ),
                    line=lineno,
                )
            )
        return issues

    # ------------------------------------------------------------------
    # Stage 6 (NEW): Schema contract
    # ------------------------------------------------------------------

    def validate_schema_contract(
        self, code: str, manifest: ToolManifest
    ) -> list[ValidationIssue]:
        """Compare ``run()`` parameter names with ``manifest.input_schema``
        keys and flag mismatches."""
        issues: list[ValidationIssue] = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues

        run_node = _find_run_function(tree)
        if run_node is None:
            # Entry-point validation will catch the missing run function.
            return issues

        # Gather parameter names from run() (exclude 'self' just in case).
        param_names: set[str] = set()
        for arg in run_node.args.args:
            if arg.arg != "self":
                param_names.add(arg.arg)
        # Also include keyword-only args
        for arg in run_node.args.kwonlyargs:
            param_names.add(arg.arg)

        if not manifest.input_schema:
            return issues

        schema_keys: set[str] = set(manifest.input_schema.keys())

        params_not_in_schema = param_names - schema_keys
        schema_not_in_params = schema_keys - param_names

        for p in sorted(params_not_in_schema):
            issues.append(
                ValidationIssue(
                    stage="schema_contract",
                    severity="error",
                    message=(
                        f"Parameter '{p}' in run() is not declared in "
                        f"manifest input_schema."
                    ),
                    line=run_node.lineno,
                )
            )
        for k in sorted(schema_not_in_params):
            issues.append(
                ValidationIssue(
                    stage="schema_contract",
                    severity="error",
                    message=(
                        f"Schema key '{k}' in manifest input_schema has no "
                        f"corresponding parameter in run()."
                    ),
                    line=run_node.lineno,
                )
            )
        return issues

    # ------------------------------------------------------------------
    # Stage 7 (NEW): Return consistency
    # ------------------------------------------------------------------

    def validate_return_consistency(self, code: str) -> list[ValidationIssue]:
        """Check that return statements inside ``run()`` are consistent with
        its declared return-type annotation."""
        issues: list[ValidationIssue] = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues

        run_node = _find_run_function(tree)
        if run_node is None:
            return issues

        ann_name = _get_return_annotation_name(run_node)
        if ann_name is None:
            return issues  # no annotation – nothing to check

        # Walk all Return nodes inside run()
        for node in ast.walk(run_node):
            if not isinstance(node, ast.Return):
                continue
            value = node.value
            if value is None:
                continue

            if ann_name == "dict" and isinstance(value, ast.Constant) and isinstance(value.value, str):
                issues.append(
                    ValidationIssue(
                        stage="return_consistency",
                        severity="warning",
                        message=(
                            "run() is annotated to return 'dict' but this "
                            "return statement returns a bare string."
                        ),
                        line=node.lineno,
                    )
                )
            elif ann_name == "str" and isinstance(value, ast.Dict):
                issues.append(
                    ValidationIssue(
                        stage="return_consistency",
                        severity="warning",
                        message=(
                            "run() is annotated to return 'str' but this "
                            "return statement returns a dict literal."
                        ),
                        line=node.lineno,
                    )
                )
        return issues

    # ------------------------------------------------------------------
    # Stage 8 (NEW): Dependency completeness
    # ------------------------------------------------------------------

    def validate_dependency_completeness(
        self, code: str, requirements: list[str]
    ) -> list[ValidationIssue]:
        """For every non-stdlib import, verify it appears in *requirements*.
        Unlike validate_imports this emits *warnings* rather than errors, and
        is intended to catch potentially missing transitive dependencies."""
        issues: list[ValidationIssue] = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues

        stdlib = _get_stdlib_modules()
        norm_reqs: set[str] = set()
        for req in requirements:
            bare = re.split(r"[>=<!;\[\]]", req, maxsplit=1)[0].strip()
            if bare:
                norm_reqs.add(_normalize_package_name(bare))

        imported = _extract_imported_root_modules(tree)
        seen: set[str] = set()
        for mod_name, lineno in imported:
            normalized = _normalize_package_name(mod_name)
            if normalized in seen:
                continue
            seen.add(normalized)

            if mod_name in stdlib:
                continue
            if _is_dependency_satisfied(mod_name, norm_reqs, self.llm):
                continue
            issues.append(
                ValidationIssue(
                    stage="dependency_completeness",
                    severity="warning",
                    message=(
                        f"Import '{mod_name}' is not in stdlib and not found "
                        f"in requirements; it may be a missing dependency."
                    ),
                    line=lineno,
                )
            )
        return issues

    # ------------------------------------------------------------------
    # Stage 9 (NEW): Dead code detection
    # ------------------------------------------------------------------

    def validate_dead_code(self, code: str) -> list[ValidationIssue]:
        """Detect (a) imports that are never referenced and (b) top-level
        assignments whose targets are never referenced elsewhere."""
        issues: list[ValidationIssue] = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues

        # Collect all Name.id and Attribute.attr referenced in the *entire*
        # module (we will then subtract the definition sites).
        all_refs = _collect_names_and_attrs(tree)

        # --- (a) Unused imports ---
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    bound_name = alias.asname if alias.asname else alias.name.split(".")[0]
                    if bound_name not in all_refs:
                        issues.append(
                            ValidationIssue(
                                stage="dead_code",
                                severity="warning",
                                message=f"Import '{alias.name}' is never used.",
                                line=node.lineno,
                            )
                        )
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    bound_name = alias.asname if alias.asname else alias.name
                    if bound_name not in all_refs:
                        issues.append(
                            ValidationIssue(
                                stage="dead_code",
                                severity="warning",
                                message=(
                                    f"Import '{bound_name}' (from "
                                    f"'{node.module}') is never used."
                                ),
                                line=node.lineno,
                            )
                        )

        # --- (b) Unused top-level assignments ---
        # We look at simple Name targets in top-level Assign / AnnAssign.
        # We exclude names starting with '_' (conventionally private/unused).
        for node in tree.body:
            targets: list[str] = []
            lineno = getattr(node, "lineno", None)
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        targets.append(target.id)
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name):
                    targets.append(node.target.id)

            for tgt_name in targets:
                if tgt_name.startswith("_"):
                    continue
                # Count how many times this name appears in all_refs.
                # The assignment itself contributes one reference (the Name
                # node in the target), so we need to check whether the name
                # is used *anywhere else* in the tree apart from the
                # assignment target.  A quick heuristic: count occurrences
                # across the whole tree.
                count = 0
                for ref_node in ast.walk(tree):
                    if isinstance(ref_node, ast.Name) and ref_node.id == tgt_name:
                        count += 1
                # The assignment target itself is 1 occurrence; if total <= 1
                # the variable is never read.
                if count <= 1:
                    issues.append(
                        ValidationIssue(
                            stage="dead_code",
                            severity="warning",
                            message=f"Top-level variable '{tgt_name}' is assigned but never used.",
                            line=lineno,
                        )
                    )
        return issues

    # ------------------------------------------------------------------
    # Stage 10 (NEW): Complexity guard
    # ------------------------------------------------------------------

    def validate_complexity(self, code: str) -> list[ValidationIssue]:
        """Calculate cyclomatic complexity of ``run()`` and flag if > 15."""
        issues: list[ValidationIssue] = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues

        run_node = _find_run_function(tree)
        if run_node is None:
            return issues

        complexity = 1  # base complexity
        for node in ast.walk(run_node):
            if isinstance(node, ast.If):
                complexity += 1
            elif isinstance(node, ast.For):
                complexity += 1
            elif isinstance(node, ast.While):
                complexity += 1
            elif isinstance(node, ast.ExceptHandler):
                complexity += 1
            elif isinstance(node, ast.With):
                complexity += 1
            elif isinstance(node, ast.Assert):
                complexity += 1
            elif isinstance(node, ast.IfExp):
                # ternary expression
                complexity += 1
            elif isinstance(node, ast.BoolOp):
                # Each 'and' / 'or' adds (num_values - 1) decision points
                complexity += len(node.values) - 1

        if complexity > 15:
            issues.append(
                ValidationIssue(
                    stage="complexity",
                    severity="warning",
                    message=(
                        f"run() has a cyclomatic complexity of {complexity} "
                        f"(threshold: 15). Consider refactoring."
                    ),
                    line=run_node.lineno,
                )
            )
        return issues

    # ------------------------------------------------------------------
    # Stage 11 (NEW): File encoding checks
    # ------------------------------------------------------------------

    def validate_file_encoding(self, code: str) -> list[ValidationIssue]:
        """Detect ``open()`` calls in text mode without explicit ``encoding=``."""
        issues: list[ValidationIssue] = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Name) and node.func.id == "open"):
                continue

            # Skip if encoding= already present
            if any(kw.arg == "encoding" for kw in node.keywords):
                continue

            # Skip binary modes
            is_binary = False
            if len(node.args) >= 2:
                mode_arg = node.args[1]
                if isinstance(mode_arg, ast.Constant) and isinstance(mode_arg.value, str):
                    if "b" in mode_arg.value:
                        is_binary = True
            for kw in node.keywords:
                if kw.arg == "mode":
                    if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        if "b" in kw.value.value:
                            is_binary = True
            if is_binary:
                continue

            issues.append(
                ValidationIssue(
                    stage="file_encoding",
                    severity="warning",
                    message=(
                        "open() call without explicit encoding= parameter. "
                        "Consider adding encoding='utf-8' for cross-platform compatibility."
                    ),
                    line=node.lineno,
                )
            )
        return issues

    # ------------------------------------------------------------------
    # Stage 12 (NEW): Network timeout checks
    # ------------------------------------------------------------------

    def validate_network_timeouts(self, code: str) -> list[ValidationIssue]:
        """Detect ``requests.get/post/put/delete/head/patch/request`` calls
        without a ``timeout=`` parameter."""
        issues: list[ValidationIssue] = []
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return issues

        target_methods = {"get", "post", "put", "delete", "head", "patch", "request"}

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "requests"
                and node.func.attr in target_methods
            ):
                continue

            # Skip if timeout= already present
            if any(kw.arg == "timeout" for kw in node.keywords):
                continue

            issues.append(
                ValidationIssue(
                    stage="network_timeouts",
                    severity="warning",
                    message=(
                        f"requests.{node.func.attr}() call without timeout= parameter. "
                        f"Add timeout=30 to prevent hanging requests."
                    ),
                    line=node.lineno,
                )
            )
        return issues

    # ------------------------------------------------------------------
    # Stage 13: Ruff format + lint (existing)
    # ------------------------------------------------------------------

    def run_ruff_formatting_and_lint(
        self, code: str
    ) -> tuple[str, list[ValidationIssue]]:
        issues: list[ValidationIssue] = []
        formatted_code = code

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "tool_temp.py"
            file_path.write_text(code, encoding="utf-8")

            # Run ruff format
            try:
                subprocess.run(
                    ["ruff", "format", str(file_path)], capture_output=True, check=False
                )
                formatted_code = file_path.read_text(encoding="utf-8")
            except Exception as e:
                issues.append(
                    ValidationIssue(
                        stage="formatting",
                        severity="warning",
                        message=f"Ruff format run failed: {e!s}",
                    )
                )

            # Run ruff check
            try:
                result = subprocess.run(
                    ["ruff", "check", "--output-format=json", str(file_path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.stdout:
                    try:
                        ruff_diagnostics = json.loads(result.stdout)
                        for d in ruff_diagnostics:
                            issues.append(
                                ValidationIssue(
                                    stage="lint",
                                    severity="warning",
                                    message=f"[{d.get('code')}] {d.get('message')}",
                                    line=d.get("location", {}).get("row"),
                                )
                            )
                    except Exception:
                        pass
            except Exception as e:
                issues.append(
                    ValidationIssue(
                        stage="lint",
                        severity="warning",
                        message=f"Ruff check execution failed: {e!s}",
                    )
                )

        return formatted_code, issues

    # ------------------------------------------------------------------
    # Orchestrator: run all stages
    # ------------------------------------------------------------------

    def validate(self, tool: GeneratedTool) -> ValidationResult:
        log = logger.bind(component="validator", tool_name=tool.name)
        log.debug("validator_checking_started")

        all_issues: list[ValidationIssue] = []

        # 1. Syntax check
        syntax_issues = self.validate_syntax(tool.code)
        all_issues.extend(syntax_issues)
        if any(iss.severity == "error" for iss in syntax_issues):
            return ValidationResult(is_valid=False, issues=all_issues)

        # 2. Policy/Guardrails check
        from nanoscrypt.core.guardrails import PolicyEngine

        policy_engine = PolicyEngine()
        violations = policy_engine.check_tool(tool)
        for v in violations:
            all_issues.append(
                ValidationIssue(
                    stage="policy",
                    severity=v["severity"],
                    message=v["message"],
                    line=v["line"],
                )
            )

        # 3. Security Check (standard AST checks)
        security_issues = self.validate_security(tool.code)
        all_issues.extend(security_issues)

        # 4. Entry point Check
        entry_issues = self.validate_entry_point(tool.code)
        all_issues.extend(entry_issues)

        # 5. Import availability (NEW)
        import_issues = self.validate_imports(tool.code, tool.requirements)
        all_issues.extend(import_issues)

        # 6. Schema contract (NEW)
        schema_issues = self.validate_schema_contract(tool.code, tool.manifest)
        all_issues.extend(schema_issues)

        # 7. Return consistency (NEW)
        return_issues = self.validate_return_consistency(tool.code)
        all_issues.extend(return_issues)

        # 8. Dependency completeness (NEW)
        dep_issues = self.validate_dependency_completeness(tool.code, tool.requirements)
        all_issues.extend(dep_issues)

        # 9. Dead code detection (NEW)
        dead_code_issues = self.validate_dead_code(tool.code)
        all_issues.extend(dead_code_issues)

        # 10. Complexity guard (NEW)
        complexity_issues = self.validate_complexity(tool.code)
        all_issues.extend(complexity_issues)

        # 11. File encoding checks (NEW)
        encoding_issues = self.validate_file_encoding(tool.code)
        all_issues.extend(encoding_issues)

        # 12. Network timeout checks (NEW)
        timeout_issues = self.validate_network_timeouts(tool.code)
        all_issues.extend(timeout_issues)

        # 13. Ruff Format + Lint
        formatted, lint_issues = self.run_ruff_formatting_and_lint(tool.code)
        all_issues.extend(lint_issues)

        # If any validation issue is of severity "error", validation fails
        is_valid = not any(iss.severity == "error" for iss in all_issues)

        log.info(
            "validator_checking_completed",
            is_valid=is_valid,
            issues_count=len(all_issues),
        )
        return ValidationResult(
            is_valid=is_valid, issues=all_issues, formatted_code=formatted
        )
