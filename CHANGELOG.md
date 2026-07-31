# Changelog

All notable changes to the Nanoscrypt project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-07-31

### Added
- **Dynamic Workspace Path Resolution**: Configured system prompt templates (`generator.py`, `repair.py`) to resolve target file/directory creation relative to the root project workspace rather than temporary execution subdirectories.
- **Runtime Environment Context Injection**: Updated `RuntimeManager.execute_tool` in `runtime.py` to pass the `PROJECT_ROOT` environment variable during tool subprocess execution.

### Changed
- **AST Security Policy Compliance**: Standardized prompt code templates to use `from pathlib import Path` exclusively. Removed `import os` from tool generation snippets to maintain 100% compliance with `SecurityASTVisitor.BLOCKED_IMPORTS`.
- **Parameter Variable Name Resolution**: Updated tool generation guidelines so parameter variable names (e.g. `file_path`, `folder_path`) are properly passed to `Path()` constructors, eliminating `NameError` runtime failures.
- **Directory Safety Guards**: Added target path directory validation (`target_path.is_dir()`) to prevent generated file-writing tools from calling `unlink()` on directory paths, preventing Windows `[WinError 5] Access is denied` exceptions.
- **Token Usage Tracking Fallback**: Enhanced `LiteLLMProvider` in `litellm_provider.py` with fallback token counting (`count_tokens()`) for local LLM providers (e.g., Ollama) that omit token usage metadata.
- **Planner Routing Rules**: Updated `planner.py` decision rules to enforce `generate_tool` for new capability requests rather than attempting invalid parameter reuse on existing registered tools.

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
