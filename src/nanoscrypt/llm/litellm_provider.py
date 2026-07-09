from typing import Any
import litellm
from pydantic import BaseModel
from nanoscrypt.llm.base import LLMProvider

class LiteLLMProvider(LLMProvider):
    """LiteLLM implementation of the LLMProvider interface supporting 100+ providers."""

    def __init__(self, default_model: str, temperature: float = 0.2, max_tokens: int = 4096):
        self.default_model = default_model
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def generate(self, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Inject default options
        model = kwargs.pop("model", self.default_model)
        temp = kwargs.pop("temperature", self.temperature)
        tokens = kwargs.pop("max_tokens", self.max_tokens)

        response = await litellm.acompletion(
            model=model,
            messages=messages,
            temperature=temp,   
            max_tokens=tokens,
            **kwargs
        )
        return response.choices[0].message.content or ""

    async def generate_structured(
        self, 
        prompt: str, 
        response_model: Any, 
        system_prompt: str | None = None, 
        **kwargs: Any
    ) -> Any:
        """Calls the LLM and forces a structured output using Pydantic schemas."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        model = kwargs.pop("model", self.default_model)
        temp = kwargs.pop("temperature", self.temperature)
        tokens = kwargs.pop("max_tokens", self.max_tokens)

        # Uses LiteLLM's structured output integration
        response = await litellm.acompletion(
            model=model,
            messages=messages,
            temperature=temp,
            max_tokens=tokens,
            response_format=response_model,
            **kwargs
        )
        
        # Parse output directly back matching the Pydantic class
        raw_content = response.choices[0].message.content or ""
        if issubclass(response_model, BaseModel):
            return response_model.model_validate_json(raw_content)
        return raw_content
