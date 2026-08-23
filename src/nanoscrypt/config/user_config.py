import os
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:
    import tomli as tomllib

# The root user configuration directory: ~/.nanoscrypt/config.toml
GLOBAL_CONFIG_DIR = Path.home() / ".nanoscrypt"
GLOBAL_CONFIG_FILE = GLOBAL_CONFIG_DIR / "config.toml"

# Supported Providers and their default model templates & env variables
SUPPORTED_PROVIDERS = {
    "openai": {
        "name": "OpenAI",
        "default_model": "gpt-4o",
        "popular_models": ["gpt-4o", "gpt-4o-mini", "o1", "o3-mini", "gpt-4-turbo"],
        "api_key_env": "OPENAI_API_KEY",
        "requires_key": True,
        "api_base_env": None,
    },
    "anthropic": {
        "name": "Anthropic",
        "default_model": "claude-3-5-sonnet-20241022",
        "popular_models": [
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
        ],
        "api_key_env": "ANTHROPIC_API_KEY",
        "requires_key": True,
        "api_base_env": None,
    },
    "gemini": {
        "name": "Google Gemini",
        "default_model": "gemini/gemini-1.5-pro",
        "popular_models": [
            "gemini/gemini-1.5-pro",
            "gemini/gemini-1.5-flash",
            "gemini/gemini-2.0-flash-exp",
        ],
        "api_key_env": "GEMINI_API_KEY",
        "requires_key": True,
        "api_base_env": None,
    },
    "groq": {
        "name": "Groq",
        "default_model": "groq/llama-3.3-70b-versatile",
        "popular_models": [
            "groq/llama-3.3-70b-versatile",
            "groq/llama-3.1-8b-instant",
            "groq/mixtral-8x7b-32768",
            "groq/deepseek-r1-distill-llama-70b",
        ],
        "api_key_env": "GROQ_API_KEY",
        "requires_key": True,
        "api_base_env": None,
    },
    "deepseek": {
        "name": "DeepSeek",
        "default_model": "deepseek/deepseek-chat",
        "popular_models": [
            "deepseek/deepseek-chat",
            "deepseek/deepseek-reasoner",
        ],
        "api_key_env": "DEEPSEEK_API_KEY",
        "requires_key": True,
        "api_base_env": None,
    },
    "openrouter": {
        "name": "OpenRouter",
        "default_model": "openrouter/anthropic/claude-3.5-sonnet",
        "popular_models": [
            "openrouter/anthropic/claude-3.5-sonnet",
            "openrouter/meta-llama/llama-3.3-70b-instruct",
            "openrouter/deepseek/deepseek-r1",
            "openrouter/openai/gpt-4o",
        ],
        "api_key_env": "OPENROUTER_API_KEY",
        "requires_key": True,
        "api_base_env": None,
    },
    "ollama": {
        "name": "Ollama (Local)",
        "default_model": "ollama/qwen2.5-coder",
        "popular_models": [
            "ollama/qwen2.5-coder",
            "ollama/llama3.2",
            "ollama/deepseek-r1:7b",
            "ollama/mistral",
        ],
        "api_key_env": None,
        "requires_key": False,
        "api_base_env": "OLLAMA_API_BASE",
    },
    "custom": {
        "name": "Custom / Other LiteLLM Provider",
        "default_model": "custom",
        "popular_models": [],
        "api_key_env": "CUSTOM_API_KEY",
        "requires_key": False,
        "api_base_env": None,
    },
}


def load_global_config() -> dict[str, Any]:
    """Reads the user root configuration from ~/.nanoscrypt/config.toml."""
    if not GLOBAL_CONFIG_FILE.exists():
        return {}
    try:
        with open(GLOBAL_CONFIG_FILE, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def save_global_config(
    provider: str,
    api_key: str | None = None,
    model: str | None = None,
    api_base: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> Path:
    """Saves provider, API Key, and model settings to ~/.nanoscrypt/config.toml."""
    GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    current = load_global_config()

    llm_section = current.get("llm", {})
    llm_section["provider"] = provider
    if model:
        llm_section["model"] = model
    if api_key:
        llm_section["api_key"] = api_key
    if api_base:
        llm_section["api_base"] = api_base

    current["llm"] = llm_section

    if extra_env:
        env_section = current.get("env", {})
        env_section.update(extra_env)
        current["env"] = env_section

    # Serialize to TOML format cleanly
    lines = ["[llm]"]
    lines.append(f'provider = "{llm_section.get("provider", "ollama")}"')
    if "model" in llm_section:
        lines.append(f'model = "{llm_section["model"]}"')
    if "api_key" in llm_section:
        lines.append(f'api_key = "{llm_section["api_key"]}"')
    if "api_base" in llm_section:
        lines.append(f'api_base = "{llm_section["api_base"]}"')

    if "env" in current and current["env"]:
        lines.append("\n[env]")
        for k, v in current["env"].items():
            lines.append(f'{k} = "{v}"')

    lines.append("")
    GLOBAL_CONFIG_FILE.write_text("\n".join(lines), encoding="utf-8")
    return GLOBAL_CONFIG_FILE


def apply_global_env():
    """Exports API keys and environment variables stored in ~/.nanoscrypt/config.toml into os.environ."""
    data = load_global_config()
    llm_data = data.get("llm", {})
    provider = llm_data.get("provider")
    api_key = llm_data.get("api_key")
    api_base = llm_data.get("api_base")

    if provider and provider in SUPPORTED_PROVIDERS:
        prov_info = SUPPORTED_PROVIDERS[provider]
        env_var = prov_info.get("api_key_env")
        if env_var and api_key and env_var not in os.environ:
            os.environ[env_var] = api_key

        base_var = prov_info.get("api_base_env")
        if base_var and api_base and base_var not in os.environ:
            os.environ[base_var] = api_base

    # Direct generic API Key env variable
    if api_key and "NANOSCRYPT_LLM__API_KEY" not in os.environ:
        os.environ["NANOSCRYPT_LLM__API_KEY"] = api_key

    # Custom extra envs
    env_section = data.get("env", {})
    for k, v in env_section.items():
        if k not in os.environ:
            os.environ[k] = str(v)


def is_configured() -> bool:
    """Checks if the user has already configured a provider and necessary keys or local model."""
    # Check if env vars are already active
    for prov in SUPPORTED_PROVIDERS.values():
        env_var = prov.get("api_key_env")
        if env_var and os.environ.get(env_var):
            return True

    if os.environ.get("NANOSCRYPT_LLM__API_KEY"):
        return True

    # Check if global config file exists with a provider configured
    cfg = load_global_config()
    llm = cfg.get("llm", {})
    if "provider" in llm:
        provider = llm["provider"]
        if provider == "ollama":
            return True
        if llm.get("api_key"):
            return True

    return False
