import pytest

from nanoscrypt.cli import setup


@pytest.mark.parametrize(
    ("entered_key", "expected_key"),
    [("test-nvidia-api-key", "test-nvidia-api-key"), ("", None)],
)
def test_custom_provider_collects_key_separately_from_api_base(
    monkeypatch, entered_key, expected_key
):
    responses = iter(
        [
            "8",
            entered_key,
            "nvidia_nim/example/model",
            "",
        ]
    )
    saved = {}

    def save_config(**kwargs):
        saved.update(kwargs)
        return "config.toml"

    monkeypatch.setattr(
        setup.Prompt, "ask", lambda *_args, **_kwargs: next(responses)
    )
    monkeypatch.setattr(setup, "save_global_config", save_config)

    assert setup.prompt_provider_and_key(force=True)
    assert saved == {
        "provider": "custom",
        "api_key": expected_key,
        "model": "nvidia_nim/example/model",
        "api_base": None,
    }
