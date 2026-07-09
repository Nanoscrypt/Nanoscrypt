from pathlib import Path
from typing import Any
try:
    import tomllib
except ImportError:
    import tomli as tomllib
from pydantic import Field, BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

class LLMSettings(BaseModel):
    model: str = "ollama/qwen2.5-coder"
    temperature: float = 0.2
    max_tokens: int = 4096

class RuntimeSettings(BaseModel):
    timeout_seconds: int = 30
    max_memory_mb: int = 512
    cleanup_after: bool = True
    workspace_root: str = "./workspaces"

class RegistrySettings(BaseModel):
    database_url: str = "sqlite+aiosqlite:///./registry/tools.db"
    tools_dir: str = "./generated_tools"

class LoggingSettings(BaseModel):
    level: str = "INFO"
    json_output: bool = False

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NANOSCRYPT_",
        env_nested_delimiter="__",
        extra="ignore"
    )
    
    llm: LLMSettings = Field(default_factory=LLMSettings)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    registry: RegistrySettings = Field(default_factory=RegistrySettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

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
            logging.warning(f"Failed to parse TOML configuration from {config_path}: {e}")
            
    # Load settings using the dictionary from TOML, env variables override this
    return Settings(**toml_data)

settings = load_settings()
