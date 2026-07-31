# Changelog

All notable changes to the Nanoscrypt project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-07-31

### Added
- **Dynamic Workspace Root Path Resolution**: Enforced pure `pathlib.Path` root workspace traversal inside `generator.py` and `repair.py` system prompts (`cwd.parts.index("workspaces")`) so synthesized tools resolve relative target paths directly to the project root directory rather than temporary execution subdirectories.
- **Runtime Environment Context Injection**: Injected `PROJECT_ROOT` environment variable (`env["PROJECT_ROOT"]`) inside `RuntimeManager.execute_tool` (`runtime.py`) during `subprocess.run` tool invocation.
- **Token Estimation Fallback**: Upgraded `LiteLLMProvider` (`litellm_provider.py`) to automatically estimate token usage (`self.count_tokens()`) when local LLM servers (e.g. Ollama `ollama/qwen2.5-coder`) omit token usage statistics in response headers.
- **Target Path Directory Safety Guards**: Added target path validation (`target_path.is_dir()`) and non-empty string checks in prompt standards to prevent generated file tools from calling `unlink()` on directory paths.

### Fixed
- **AST Security Policy Violation (`import os`)**: Resolved AST validation failures (`Import of dangerous module 'os' is blocked by policy`) by removing `import os` references from system prompt code templates in `generator.py` and `repair.py`, standardizing exclusively on `from pathlib import Path`.
- **Parameter Variable Propagation (`NameError`)**: Resolved `NameError: name 'file_or_folder_path' is not defined` by updating system prompt instructions in `generator.py` and `repair.py` to ensure target path constructors receive the function's actual parameter variable (e.g. `Path(file_path)` or `Path(folder_path)`).
- **Windows Permission Exceptions (`[WinError 5] Access is denied`)**: Prevented Windows permission errors caused by unlinking directory targets when prompts omit target file parameters by enforcing `if target_path.is_dir(): return {"error": "..."}` guards in `generator.py`, `repair.py`, and default tool implementations (`create_file/v1/tool.py`).
- **Missing Module Import in Runtime (`runtime.py`)**: Fixed `NameError: name 'os' is not defined` inside `runtime.py` by adding `import os` to top-level runtime imports.
- **Session Workspace Teardown File Loss**: Fixed issue where files and directories created by tools were wiped out by `cleanup_workspace` upon session completion by ensuring tools create target outputs directly in the root workspace directory.

### Changed
- **Planner Routing Guidelines (`planner.py`)**: Refined decision rules for `reuse_tool` vs `generate_tool` in `planner.py` to force `generate_tool` when the user requests generating a new tool by name, preventing invalid parameter reuse on existing registered tools (e.g. attempting to pass `file_path="test_tool_dir/"` to `create_file`).
- **Tool Implementations (`create_file` & `create_folder`)**: Synchronized version 1 implementations of `create_file` and `create_folder` in both disk storage (`generated_tools/`) and SQLite database (`registry/tools.db`) with pure `pathlib.Path` root workspace path resolution.

## [0.1.0] - 2026-07-18

### Added
- **Windows Console Encoding Safe-Guard**: Dynamically reconfigure standard output streams (`sys.stdout`/`sys.stderr`) to UTF-8 on system startup inside `cli/main.py` to prevent cp1252 encoding crashes when rendering modern terminal formatting characters.
- **Dynamic LLM-Driven Dependency Resolver**: Integrated dynamic LLM-based verification to resolve Python module imports to their respective distribution packages (e.g., mapping `fitz` -> `pymupdf` or `PIL` -> `pillow`) at runtime.
- **Google CAPTCHA Bypass Guidelines**: Configured standard prompt-level fallbacks in `generator.py` and `repair.py` systems to prioritize DuckDuckGo HTML search and desktop User-Agent headers when scraping, preventing automated requests from getting trapped in Google CAPTCHA redirects (`/sorry/index`).
- **Shared Virtual Environment Cache**: Introduced a centralized shared virtual environment (`shared_env`) inside `runtime.py`. It tracks installed dependencies in a local index file, ensuring packages (like `requests` or `pandas`) are installed once and reused instantly across all generated tools instead of downloading from scratch on every run.
- **Enterprise-Grade Prompt Engineering Overhaul**: Completely rewrote all three LLM system prompts (`generator.py`, `repair.py`, `planner.py`) with structured sections covering:
  - Type safety with `isinstance()` guards and typing annotations
  - Network resilience with exponential backoff retry loops (3 attempts, 2s/4s/8s)
  - Isolated logging (stderr only, stdout reserved for JSON output)
  - Resource cleanup enforcement via context managers
  - Advanced unit test assertions (structural dict verification, success + error path coverage)
  - CAPTCHA/bot detection avoidance with DuckDuckGo fallback patterns
  - File format detection rules in the planner for accurate dependency hints
  - Actionable tool purpose specification guidelines to reduce vague code generation

### Changed
- **Type-Safe Parameter Extractor Fallbacks**: Refactored the orchestrator parameter parser in `orchestrator.py` to check inputs against target tool schemas. If parameters are missing during validation passes, the engine dynamically injects type-safe dummy values to bypass false-positive Repair Loop traps.
- **Decoupled Package Registries**: Deleted static package mapping configurations and restructured `validator.py` and `postprocessor.py` to execute LLM queries dynamically to verify imported module package satisfying rules.
- **Unit Test Coverage**: Patched validator unit tests inside `tests/unit/test_validator.py` to mock LLM interactions, ensuring backward compatibility with the new dynamic resolver.

### Removed
- **Static Registries**: Deleted the hardcoded configuration file `src/nanoscrypt/config/package_mappings.json` and associated static mapping dictionaries from `validator.py` and `postprocessor.py`.
