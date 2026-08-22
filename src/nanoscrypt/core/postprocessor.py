import ast
import re
import sys
from copy import deepcopy

import structlog

from nanoscrypt.models.tool import GeneratedTool

logger = structlog.get_logger()

# Standard library modules that LLMs sometimes accidentally include in requirements
STDLIB_MODULES = frozenset({
    "re", "json", "typing", "pathlib", "os", "sys", "math", "datetime",
    "collections", "itertools", "functools", "hashlib", "hmac", "secrets",
    "uuid", "copy", "io", "string", "textwrap", "unicodedata", "struct",
    "codecs", "enum", "dataclasses", "abc", "contextlib", "decimal",
    "fractions", "random", "statistics", "operator", "logging", "warnings",
    "traceback", "unittest", "doctest", "pdb", "timeit", "argparse",
    "configparser", "csv", "sqlite3", "html", "xml", "urllib", "http",
    "email", "base64", "binascii", "shutil", "glob", "fnmatch", "tempfile",
    "gzip", "zipfile", "tarfile", "time", "calendar", "threading",
    "multiprocessing", "subprocess", "socket", "signal", "mmap",
    "platform", "inspect", "dis", "ast", "token", "tokenize", "pprint",
    "difflib", "pickle", "shelve", "marshal", "dbm", "webbrowser",
})

# Binary file modes that don't need encoding
BINARY_MODES = {"rb", "wb", "ab", "r+b", "w+b", "a+b", "rb+", "wb+", "ab+"}

# Network methods on the requests library that need timeout
REQUESTS_METHODS = {"get", "post", "put", "delete", "head", "patch", "request"}


class _EncodingFixer(ast.NodeTransformer):
    """AST transformer that injects encoding='utf-8' into open() calls missing it."""

    def __init__(self) -> None:
        self.fixes_applied = 0

    def visit_Call(self, node: ast.Call) -> ast.Call:
        self.generic_visit(node)

        # Match open(...) calls (bare name)
        if not (isinstance(node.func, ast.Name) and node.func.id == "open"):
            return node

        # Check if encoding= already present
        if any(kw.arg == "encoding" for kw in node.keywords):
            return node

        # Check if binary mode -- look at the 'mode' argument
        if self._is_binary_mode(node):
            return node

        # Inject encoding='utf-8'
        node.keywords.append(
            ast.keyword(arg="encoding", value=ast.Constant(value="utf-8"))
        )
        self.fixes_applied += 1
        return node

    @staticmethod
    def _is_binary_mode(node: ast.Call) -> bool:
        """Check if the open() call uses a binary mode."""
        # Check positional args: open(path, mode) -- mode is the 2nd arg
        if len(node.args) >= 2:
            mode_arg = node.args[1]
            if isinstance(mode_arg, ast.Constant) and isinstance(mode_arg.value, str):
                if "b" in mode_arg.value:
                    return True

        # Check keyword arg: open(path, mode='rb')
        for kw in node.keywords:
            if kw.arg == "mode":
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    if "b" in kw.value.value:
                        return True
        return False


class _TimeoutFixer(ast.NodeTransformer):
    """AST transformer that injects timeout=30 into requests method calls missing it."""

    def __init__(self) -> None:
        self.fixes_applied = 0

    def visit_Call(self, node: ast.Call) -> ast.Call:
        self.generic_visit(node)

        # Match requests.get(...), requests.post(...), etc.
        if not (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "requests"
            and node.func.attr in REQUESTS_METHODS
        ):
            return node

        # Check if timeout= already present
        if any(kw.arg == "timeout" for kw in node.keywords):
            return node

        # Inject timeout=30
        node.keywords.append(
            ast.keyword(arg="timeout", value=ast.Constant(value=30))
        )
        self.fixes_applied += 1
        return node


def fix_file_encoding(code: str) -> tuple[str, int]:
    """Add encoding='utf-8' to open() calls that are missing it (text mode only).

    Returns the (possibly modified) code string and the count of fixes applied.
    """
    try:
        tree = ast.parse(code)
        fixer = _EncodingFixer()
        new_tree = fixer.visit(tree)
        if fixer.fixes_applied > 0:
            ast.fix_missing_locations(new_tree)
            try:
                return ast.unparse(new_tree), fixer.fixes_applied
            except AttributeError:
                # Python < 3.9 fallback: use regex
                pass
        else:
            return code, 0
    except SyntaxError:
        pass

    # Regex fallback: find open(...) calls without encoding= (avoiding fitz.open, doc.open, etc.)
    count = 0
    pattern = re.compile(
        r'(?<!\.)\bopen\s*\(([^)]*)\)',
        re.DOTALL,
    )

    def _add_encoding(match: re.Match) -> str:
        nonlocal count
        inner = match.group(1)
        # Skip if already has encoding or is binary mode
        if "encoding" in inner:
            return match.group(0)
        if any(mode in inner for mode in ("'rb'", '"rb"', "'wb'", '"wb"', "'ab'", '"ab"')):
            return match.group(0)
        count += 1
        return f'open({inner.rstrip()}, encoding="utf-8")'

    result = pattern.sub(_add_encoding, code)
    return result, count


def fix_network_timeouts(code: str) -> tuple[str, int]:
    """Add timeout=30 to requests method calls that are missing it.

    Returns the (possibly modified) code string and the count of fixes applied.
    """
    try:
        tree = ast.parse(code)
        fixer = _TimeoutFixer()
        new_tree = fixer.visit(tree)
        if fixer.fixes_applied > 0:
            ast.fix_missing_locations(new_tree)
            try:
                return ast.unparse(new_tree), fixer.fixes_applied
            except AttributeError:
                # Python < 3.9 fallback: use regex
                pass
        else:
            return code, 0
    except SyntaxError:
        pass

    # Regex fallback
    count = 0
    methods_pattern = "|".join(REQUESTS_METHODS)
    pattern = re.compile(
        rf'\brequests\.(?:{methods_pattern})\s*\(([^)]*)\)',
        re.DOTALL,
    )

    def _add_timeout(match: re.Match) -> str:
        nonlocal count
        inner = match.group(1)
        if "timeout" in inner:
            return match.group(0)
        count += 1
        full = match.group(0)
        # Insert timeout=30 before the closing paren
        return full[:-1].rstrip() + ", timeout=30)"

    result = pattern.sub(_add_timeout, code)
    return result, count


def fix_pathlib_usage(code: str) -> tuple[str, bool]:
    """If code uses open() with a variable path but doesn't import pathlib, add the import.

    Returns the (possibly modified) code string and whether a fix was applied.
    """
    # Check if code uses open() at all
    if not re.search(r'\bopen\s*\(', code):
        return code, False

    # Check if pathlib is already imported
    if re.search(r'(?:from\s+pathlib\s+import|import\s+pathlib)', code):
        return code, False

    # Add the import at the top (after any existing imports or module docstring)
    lines = code.split("\n")
    insert_index = 0

    # Skip past module docstrings
    in_docstring = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if i == 0 and (stripped.startswith('"""') or stripped.startswith("'''")):
            if stripped.count('"""') >= 2 or stripped.count("'''") >= 2:
                insert_index = i + 1
                continue
            in_docstring = True
            continue
        if in_docstring:
            if '"""' in stripped or "'''" in stripped:
                in_docstring = False
                insert_index = i + 1
            continue
        # Skip past existing import lines
        if stripped.startswith("import ") or stripped.startswith("from "):
            insert_index = i + 1
        elif stripped and not stripped.startswith("#"):
            break

    lines.insert(insert_index, "from pathlib import Path")
    return "\n".join(lines), True


def fix_common_missing_imports(code: str) -> tuple[str, int]:
    """Automatically injects missing common imports (e.g. typing.Optional, datetime, shutil)
    if referenced in code but not imported, resolving F821 undefined variable errors."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code, 0

    all_names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    
    # Check what is already imported or defined
    imported_or_defined = set(dir(__builtins__))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            imported_or_defined.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported_or_defined.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported_or_defined.add(alias.asname or alias.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    imported_or_defined.add(target.id)

    missing = all_names - imported_or_defined
    injections = []

    # Check typing symbols
    typing_symbols = {"Optional", "Union", "List", "Dict", "Set", "Tuple", "Any", "Callable"}
    needed_typing = [s for s in typing_symbols if s in missing]
    if needed_typing:
        injections.append(f"from typing import {', '.join(sorted(needed_typing))}")

    # Check datetime
    if "datetime" in missing:
        injections.append("from datetime import datetime")

    # Check shutil
    if "shutil" in missing:
        injections.append("import shutil")

    # Check json
    if "json" in missing:
        injections.append("import json")

    # Check os
    if "os" in missing:
        injections.append("import os")

    # Check sys
    if "sys" in missing:
        injections.append("import sys")

    if not injections:
        return code, 0

    # Insert at top of code
    lines = code.split("\n")
    insert_idx = 0
    in_docstring = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if i == 0 and (stripped.startswith('"""') or stripped.startswith("'''")):
            if stripped.count('"""') >= 2 or stripped.count("'''") >= 2:
                insert_idx = i + 1
                continue
            in_docstring = True
            continue
        if in_docstring:
            if '"""' in stripped or "'''" in stripped:
                in_docstring = False
                insert_idx = i + 1
            continue
        if stripped.startswith("import ") or stripped.startswith("from "):
            insert_idx = i + 1
        elif stripped and not stripped.startswith("#"):
            break

    lines[insert_idx:insert_idx] = injections
    return "\n".join(lines), len(injections)


def fix_staticfiles_directory(code: str) -> tuple[str, bool]:
    """Ensures that any directory passed to StaticFiles(directory=...) is automatically created
    with Path(...).mkdir(parents=True, exist_ok=True) before StaticFiles is initialized,
    preventing Starlette runtime DirectoryDoesNotExist crashes."""
    if "StaticFiles" not in code:
        return code, False

    # Match StaticFiles(directory="...") or StaticFiles(directory='...')
    pattern = re.compile(r'StaticFiles\s*\(\s*directory\s*=\s*["\']([^"\']+)["\']', re.DOTALL)
    matches = pattern.findall(code)
    if not matches:
        return code, False

    lines = code.split("\n")
    # Find insertion point before the first StaticFiles usage or app.mount
    insert_idx = 0
    for i, line in enumerate(lines):
        if "StaticFiles" in line or "app.mount" in line:
            insert_idx = i
            break

    mkdir_statements = []
    # Ensure Path is available
    if not re.search(r'(?:from\s+pathlib\s+import|import\s+pathlib)', code):
        mkdir_statements.append("from pathlib import Path")

    for dir_path in set(matches):
        statement = f'from pathlib import Path; Path("{dir_path}").mkdir(parents=True, exist_ok=True)'
        if statement not in code:
            mkdir_statements.append(statement)

    if not mkdir_statements:
        return code, False

    lines[insert_idx:insert_idx] = mkdir_statements
    return "\n".join(lines), True


def normalize_requirements(requirements: list[str]) -> tuple[list[str], int]:
    """Clean up a requirements list: strip whitespace, remove empty lines,
    and filter out stdlib modules that were accidentally included.

    Returns the cleaned list and the count of removed entries.
    """
    cleaned: list[str] = []
    removed_count = 0

    for req in requirements:
        stripped = req.strip()
        if not stripped:
            removed_count += 1
            continue

        # Extract the bare package name (before version specifiers)
        bare_name = re.split(r"[>=<!;\[\]]", stripped, maxsplit=1)[0].strip().lower()

        if bare_name in STDLIB_MODULES:
            removed_count += 1
            continue

        cleaned.append(stripped)

    return cleaned, removed_count


def fix_test_imports(tests_code: str, tool_name: str) -> tuple[str, bool]:
    """Force tests to import from 'tool' instead of the tool's name."""
    pattern = re.compile(rf"from\s+{re.escape(tool_name)}\s+import")
    new_tests, count = pattern.subn("from tool import", tests_code)
    
    # Also handle 'import X' just in case
    pattern_direct = re.compile(rf"import\s+{re.escape(tool_name)}")
    new_tests, count2 = pattern_direct.subn("import tool", new_tests)
    
    return new_tests, (count > 0 or count2 > 0)


def fix_binary_library_requirements(code: str, requirements: list[str], llm=None) -> tuple[list[str], int]:
    """Scans code for non-stdlib module imports and queries the LLM to get the canonical package name.
    
    Returns the updated requirements list and the count of libraries added.
    """
    if not llm:
        return requirements, 0

    import ast
    import asyncio
    import concurrent.futures
    import sys

    # Parse ast to find all top-level module imports
    try:
        tree = ast.parse(code)
    except Exception:
        return requirements, 0

    imported_mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                imported_mods.add(name.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                imported_mods.add(node.module.split('.')[0])

    stdlib = sys.stdlib_module_names if sys.version_info >= (3, 10) else set()
    non_stdlib_imports = [m for m in imported_mods if m not in stdlib]

    if not non_stdlib_imports:
        return requirements, 0

    added_count = 0
    updated_reqs = list(requirements)
    norm_reqs = {r.split("[")[0].split(">")[0].split("<")[0].split("=")[0].strip().lower() for r in requirements}

    async def _resolve_package_via_llm(import_name: str) -> str | None:
        prompt = (
            f"You are a Python packaging utility.\n"
            f"Question: What is the canonical pip package name to install the python module '{import_name}'?\n"
            f"Respond ONLY with the lowercase package name (e.g. 'pymupdf' for 'fitz', 'pillow' for 'PIL', 'opencv-python' for 'cv2').\n"
            f"If the package is standard library or no external package is needed, respond with 'none'."
        )
        try:
            res = await llm.generate(prompt=prompt, temperature=0.0)
            cleaned = res.strip().lower()
            if cleaned and cleaned != "none":
                return cleaned
        except Exception:
            pass
        return None

    for mod in non_stdlib_imports:
        # Check if already satisfied
        if mod.lower() in norm_reqs:
            continue
        
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    pkg_name = executor.submit(asyncio.run, _resolve_package_via_llm(mod)).result()
            else:
                pkg_name = asyncio.run(_resolve_package_via_llm(mod))
        except Exception:
            pkg_name = None

        if pkg_name and pkg_name.lower() not in norm_reqs:
            updated_reqs.append(pkg_name)
            norm_reqs.add(pkg_name.lower())
            added_count += 1

    return updated_reqs, added_count


class CodePostProcessor:
    """Automatically fixes common issues in LLM-generated Python code before validation.

    Runs a sequence of AST-based and regex-based fixers on the code string and
    requirements list to proactively resolve encoding, timeout, and dependency issues.
    """

    def __init__(self, llm=None):
        self.llm = llm

    def process(self, tool: GeneratedTool) -> GeneratedTool:
        """Run all post-processing fixers on the tool and return a corrected copy.

        Never raises -- returns the original tool unchanged if any processing fails.
        """
        log = logger.bind(component="postprocessor", tool_name=tool.name)

        try:
            code = tool.code
            requirements = list(tool.requirements)
            fixes_summary: dict[str, int | bool] = {}

            # 1. Fix file encoding
            try:
                code, enc_fixes = fix_file_encoding(code)
                if enc_fixes:
                    fixes_summary["encoding_fixes"] = enc_fixes
            except Exception as e:
                log.warning("postprocessor_encoding_fix_failed", error=str(e))

            # 2. Fix network timeouts
            try:
                code, timeout_fixes = fix_network_timeouts(code)
                if timeout_fixes:
                    fixes_summary["timeout_fixes"] = timeout_fixes
            except Exception as e:
                log.warning("postprocessor_timeout_fix_failed", error=str(e))

            # 3. Fix pathlib usage
            try:
                code, pathlib_added = fix_pathlib_usage(code)
                if pathlib_added:
                    fixes_summary["pathlib_import_added"] = True
            except Exception as e:
                log.warning("postprocessor_pathlib_fix_failed", error=str(e))

            # 3b. Fix StaticFiles directory existence (prevents Starlette crash)
            try:
                code, static_fixed = fix_staticfiles_directory(code)
                if static_fixed:
                    fixes_summary["staticfiles_directory_created"] = True
            except Exception as e:
                log.warning("postprocessor_staticfiles_fix_failed", error=str(e))

            # 3c. Fix common missing standard imports (Optional, datetime, shutil) to prevent F821
            try:
                code, imports_fixed = fix_common_missing_imports(code)
                if imports_fixed:
                    fixes_summary["common_imports_injected"] = imports_fixed
            except Exception as e:
                log.warning("postprocessor_common_imports_fix_failed", error=str(e))

            # 4. Normalize requirements
            try:
                requirements, req_removed = normalize_requirements(requirements)
                if req_removed:
                    fixes_summary["requirements_removed"] = req_removed
            except Exception as e:
                log.warning("postprocessor_requirements_fix_failed", error=str(e))

            # 4b. Auto-fix binary library requirements
            try:
                requirements, bin_reqs_added = fix_binary_library_requirements(code, requirements, self.llm)
                if bin_reqs_added:
                    fixes_summary["binary_requirements_added"] = bin_reqs_added
            except Exception as e:
                log.warning("postprocessor_binary_reqs_fix_failed", error=str(e))

            # 5. Fix test imports
            tests_code = tool.tests
            try:
                tests_code, tests_fixed = fix_test_imports(tests_code, tool.name)
                if tests_fixed:
                    fixes_summary["test_imports_fixed"] = True
            except Exception as e:
                log.warning("postprocessor_test_import_fix_failed", error=str(e))

            # 6. Auto-synchronize manifest input_schema with actual run() parameters
            manifest = deepcopy(tool.manifest)
            try:
                tree = ast.parse(code)
                run_node = None
                for node in tree.body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run":
                        run_node = node
                        break
                if run_node and manifest:
                    param_names = [arg.arg for arg in run_node.args.args if arg.arg != "self"]
                    param_names.extend([arg.arg for arg in run_node.args.kwonlyargs])
                    new_input_schema = {}
                    for p in param_names:
                        new_input_schema[p] = manifest.input_schema.get(p, "str") if manifest.input_schema else "str"
                    manifest.input_schema = new_input_schema
                    fixes_summary["schema_synced"] = True
            except Exception as e:
                log.warning("postprocessor_schema_sync_failed", error=str(e))

            # 7. Auto-detect and include non-stdlib imports into requirements
            try:
                tree = ast.parse(code)
                stdlib = sys.stdlib_module_names if sys.version_info >= (3, 10) else set()
                imported_roots = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imported_roots.add(alias.name.split(".")[0])
                    elif isinstance(node, ast.ImportFrom):
                        if node.level == 0 and node.module:
                            imported_roots.add(node.module.split(".")[0])
                
                norm_reqs = {r.split("[")[0].split(">")[0].split("<")[0].split("=")[0].strip().lower() for r in requirements}
                for mod in imported_roots:
                    if mod not in stdlib and mod.lower() not in norm_reqs:
                        requirements.append(mod)
                        norm_reqs.add(mod.lower())
                        fixes_summary["inferred_requirements_added"] = True
            except Exception as e:
                log.warning("postprocessor_auto_reqs_failed", error=str(e))

            if fixes_summary:
                log.info("postprocessor_fixes_applied", **fixes_summary)

            # Build a new GeneratedTool with the fixed code, requirements, and manifest
            return GeneratedTool(
                name=tool.name,
                code=code,
                requirements=requirements,
                manifest=manifest,
                tests=tests_code,
                readme=tool.readme,
                created_at=tool.created_at,
            )

        except Exception as e:
            log.error("postprocessor_failed", error=str(e))
            return tool
