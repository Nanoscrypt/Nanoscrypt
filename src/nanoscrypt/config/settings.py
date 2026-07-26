from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:
    import tomli as tomllib
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseModel):
    model: str = "ollama/qwen2.5-coder"
    temperature: float = 0.2
    max_tokens: int = 131072  # Qwen 2.5 Coder 128K max
    max_output_tokens: int = 8192  # Max generation length
    retry_on_failure: bool = True
    max_retries: int = 3
    token_budget: int = 0  # 0 = unlimited


class RuntimeSettings(BaseModel):
    timeout_seconds: int = 30
    max_memory_mb: int = 512
    cleanup_after: bool = True
    workspace_root: str = "./workspaces"
    venv_cache_dir: str = "./venv_cache"  # For caching virtual environments
    capsem_enabled: bool = False

class RegistrySettings(BaseModel):
    database_url: str = "sqlite+aiosqlite:///./registry/tools.db"
    tools_dir: str = "./generated_tools"


class SecuritySettings(BaseModel):
    approval_mode: str = "interactive"  # interactive, auto, webhook
    default_risk_threshold: str = (
        "medium"  # auto-approve below this (low, medium, high, critical)
    )
    blocked_domains: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    max_file_write_mb: int = 10
    pii_detection: bool = False


class MemorySettings(BaseModel):
    enabled: bool = True
    short_term_max_entries: int = 50
    long_term_enabled: bool = True
    entity_tracking: bool = True


class ResilienceSettings(BaseModel):
    max_repair_attempts: int = 5
    retry_delay_seconds: float = 1.0
    exponential_backoff: bool = True
    circuit_breaker_threshold: int = 5
    fallback_model: str | None = None


class LoggingSettings(BaseModel):
    level: str = "INFO"
    json_output: bool = False


class HeadroomSettings(BaseModel):
    enabled: bool = True
    smart_crusher: bool = True
    code_compression: bool = True
    max_tool_output_tokens: int = 1500


class MemMachineSettings(BaseModel):
    enabled: bool = True
    base_url: str = "http://localhost:8080"
    project_id: str = "nanoscrypt"
    fallback_to_sqlite: bool = True


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NANOSCRYPT_", env_nested_delimiter="__", extra="ignore"
    )

    llm: LLMSettings = Field(default_factory=LLMSettings)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    registry: RegistrySettings = Field(default_factory=RegistrySettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    resilience: ResilienceSettings = Field(default_factory=ResilienceSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    headroom: HeadroomSettings = Field(default_factory=HeadroomSettings)
    memmachine: MemMachineSettings = Field(default_factory=MemMachineSettings)


def load_settings(config_path: Path | str | None = None) -> Settings:
    """Loads configuration settings from TOML config file and environment variables."""
    if config_path is None:
        config_path = Path("nanoscrypt.toml")
    else:
        config_path = Path(config_path)

    toml_data: dict[str, Any] = {}
    if config_path.exists():
        try:
            with open(config_path, "rb") as f:
                toml_data = tomllib.load(f)
        except Exception as e:
            # Fallback to defaults or env variables if file reading fails
            import logging

            logging.warning(
                f"Failed to parse TOML configuration from {config_path}: {e}"
            )

    # Load settings using the dictionary from TOML, env variables override this
    return Settings(**toml_data)


settings = load_settings()
