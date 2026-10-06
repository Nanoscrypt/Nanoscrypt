from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from nanoscrypt.config.settings import settings
from nanoscrypt.llm.litellm_provider import LiteLLMProvider


class StructuredAnswer(BaseModel):
    answer: str


@pytest.mark.asyncio
async def test_generate_structured_passes_configured_api_credentials(monkeypatch):
    monkeypatch.setattr(settings.llm, "api_key", "test-nvidia-api-key")
    monkeypatch.setattr(settings.llm, "api_base", "https://example.invalid/v1")
    request_kwargs = {}

    async def fake_acompletion(**kwargs):
        request_kwargs.update(kwargs)
        return SimpleNamespace(
            usage=None,
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"answer":"ok"}')
                )
            ],
        )

    monkeypatch.setattr(
        "nanoscrypt.llm.litellm_provider.litellm.acompletion",
        fake_acompletion,
    )

    result = await LiteLLMProvider("nvidia_nim/example/model").generate_structured(
        "Return a structured answer", StructuredAnswer
    )

    assert result == StructuredAnswer(answer="ok")
    assert request_kwargs["api_key"] == "test-nvidia-api-key"
    assert request_kwargs["api_base"] == "https://example.invalid/v1"
