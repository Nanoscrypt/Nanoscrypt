import ast
import re
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

            if fixes_summary:
                log.info("postprocessor_fixes_applied", **fixes_summary)

            # Build a new GeneratedTool with the fixed code and requirements
            return GeneratedTool(
                name=tool.name,
                code=code,
                requirements=requirements,
                manifest=tool.manifest,
                tests=tests_code,
                readme=tool.readme,
                created_at=tool.created_at,
            )

        except Exception as e:
            log.error("postprocessor_failed", error=str(e))
            return tool
