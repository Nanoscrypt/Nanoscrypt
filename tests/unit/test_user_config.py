import os
from pathlib import Path
import pytest
from nanoscrypt.config.user_config import (
    GLOBAL_CONFIG_DIR,
    GLOBAL_CONFIG_FILE,
    load_global_config,
    save_global_config,
    apply_global_env,
    is_configured,
    SUPPORTED_PROVIDERS,
)
from nanoscrypt.config.settings import load_settings


def test_save_and_load_global_config(tmp_path, monkeypatch):
    test_dir = tmp_path / ".nanoscrypt"
    test_file = test_dir / "config.toml"
    
    monkeypatch.setattr("nanoscrypt.config.user_config.GLOBAL_CONFIG_DIR", test_dir)
    monkeypatch.setattr("nanoscrypt.config.user_config.GLOBAL_CONFIG_FILE", test_file)

    # Save settings
    saved = save_global_config(
        provider="openai",
        api_key="sk-test-key-12345",
        model="gpt-4o",
    )
    assert saved.exists()
    
    # Load settings
    cfg = load_global_config()
    assert cfg["llm"]["provider"] == "openai"
    assert cfg["llm"]["api_key"] == "sk-test-key-12345"
    assert cfg["llm"]["model"] == "gpt-4o"


def test_apply_global_env(tmp_path, monkeypatch):
    test_dir = tmp_path / ".nanoscrypt"
    test_file = test_dir / "config.toml"
    
    monkeypatch.setattr("nanoscrypt.config.user_config.GLOBAL_CONFIG_DIR", test_dir)
    monkeypatch.setattr("nanoscrypt.config.user_config.GLOBAL_CONFIG_FILE", test_file)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    save_global_config(
        provider="openai",
        api_key="sk-test-apply-env",
        model="gpt-4o",
    )

    apply_global_env()
    assert os.environ.get("OPENAI_API_KEY") == "sk-test-apply-env"


def test_settings_merges_global_and_local(tmp_path, monkeypatch):
    test_dir = tmp_path / ".nanoscrypt"
    test_file = test_dir / "config.toml"
    
    monkeypatch.setattr("nanoscrypt.config.user_config.GLOBAL_CONFIG_DIR", test_dir)
    monkeypatch.setattr("nanoscrypt.config.user_config.GLOBAL_CONFIG_FILE", test_file)
    
    save_global_config(
        provider="anthropic",
        api_key="sk-ant-test-key",
        model="claude-3-5-sonnet-20241022",
    )

    # Load settings with non-existent local config (falls back to global)
    settings = load_settings(config_path=tmp_path / "nonexistent.toml")
    assert settings.llm.provider == "anthropic"
    assert settings.llm.api_key == "sk-ant-test-key"
    assert settings.llm.model == "claude-3-5-sonnet-20241022"


def test_supported_providers_completeness():
    assert "openai" in SUPPORTED_PROVIDERS
    assert "anthropic" in SUPPORTED_PROVIDERS
    assert "gemini" in SUPPORTED_PROVIDERS
    assert "groq" in SUPPORTED_PROVIDERS
    assert "deepseek" in SUPPORTED_PROVIDERS
    assert "openrouter" in SUPPORTED_PROVIDERS
    assert "ollama" in SUPPORTED_PROVIDERS
