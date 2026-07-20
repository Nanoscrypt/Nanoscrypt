# Changelog

All notable changes to the Nanoscrypt project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
