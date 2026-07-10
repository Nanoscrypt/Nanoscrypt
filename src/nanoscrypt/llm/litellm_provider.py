import asyncio
from typing import Any

import litellm
import structlog
from pydantic import BaseModel

from nanoscrypt.config.settings import settings
from nanoscrypt.llm.base import LLMProvider

logger = structlog.get_logger()


class LiteLLMProvider(LLMProvider):
    """Upgraded LiteLLM implementation supporting cost tracking, token counters, retries, and fallback models."""

    def __init__(
        self, default_model: str, temperature: float = 0.2, max_tokens: int = 131072
    ):
        self.default_model = default_model
        self.temperature = temperature
        self.max_tokens = max_tokens

        # Performance/usage metrics tracking
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost = 0.0

    def count_tokens(self, text: str, model: str | None = None) -> int:
        """Statically counts tokens for a string of text."""
        target_model = model or self.default_model
        try:
            return litellm.token_counter(model=target_model, text=text)
        except Exception:
            # Fallback estimation: ~4 characters per token
            return len(text) // 4

    def estimate_cost(
        self, input_tokens: int, output_tokens: int, model: str | None = None
    ) -> float:
        """Estimates model invocation costs in USD."""
        target_model = model or self.default_model
        try:
            # Get pricing dict from LiteLLM database
            pricing = litellm.get_model_info(target_model)
            input_cost = (
                pricing.get("input_cost_per_token", 0.0) or 0.0
            ) * input_tokens
            output_cost = (
                pricing.get("output_cost_per_token", 0.0) or 0.0
            ) * output_tokens
            return float(input_cost + output_cost)
        except Exception:
            return 0.0

    async def _execute_with_retry(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Executes LiteLLM completion calls with automatic backoff and fallback model rotation."""
        model = kwargs.get("model", self.default_model)
        retries = settings.llm.max_retries
        backoff = settings.resilience.retry_delay_seconds

        fallback_model = settings.resilience.fallback_model
        attempt = 0

        while attempt <= retries:
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                attempt += 1
                logger.warning(
                    "llm_completion_attempt_failed",
                    attempt=attempt,
                    model=model,
                    error=str(e),
                )
                if attempt > retries:
                    if fallback_model and model != fallback_model:
                        logger.info(
                            "llm_completion_switching_to_fallback",
                            fallback=fallback_model,
                        )
                        kwargs["model"] = fallback_model
                        # Reset attempts for fallback model
                        attempt = 0
                        model = fallback_model
                        continue
                    raise
                await asyncio.sleep(backoff * (2 ** (attempt - 1)))

    async def generate(
        self, prompt: str, system_prompt: str | None = None, **kwargs: Any
    ) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Inject default options
        model = kwargs.pop("model", self.default_model)
        temp = kwargs.pop("temperature", self.temperature)

        # Enterprise-grade distinction: max context window vs max output tokens
        tokens = kwargs.pop("max_tokens", settings.llm.max_output_tokens)

        # Execute completion inside the retry context
        response = await self._execute_with_retry(
            litellm.acompletion,
            model=model,
            messages=messages,
            temperature=temp,
            max_tokens=tokens,
            **kwargs,
        )

        # Track metrics
        try:
            usage = response.usage
            self.total_input_tokens += usage.prompt_tokens
            self.total_output_tokens += usage.completion_tokens

            # LiteLLM cost calculation helper
            cost = litellm.completion_cost(completion_response=response) or 0.0
            self.total_cost += float(cost)
        except Exception:
            pass

        return response.choices[0].message.content or ""

    async def generate_structured(
        self,
        prompt: str,
        response_model: Any,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Calls the LLM and forces a structured output using Pydantic schemas, with retry and fallback support."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        model = kwargs.pop("model", self.default_model)
        temp = kwargs.pop("temperature", self.temperature)
        tokens = kwargs.pop("max_tokens", settings.llm.max_output_tokens)

        response = await self._execute_with_retry(
            litellm.acompletion,
            model=model,
            messages=messages,
            temperature=temp,
            max_tokens=tokens,
            response_format=response_model,
            **kwargs,
        )

        # Track metrics
        try:
            usage = response.usage
            self.total_input_tokens += usage.prompt_tokens
            self.total_output_tokens += usage.completion_tokens
            cost = litellm.completion_cost(completion_response=response) or 0.0
            self.total_cost += float(cost)
        except Exception:
            pass

        raw_content = response.choices[0].message.content or ""
        if issubclass(response_model, BaseModel):
            return response_model.model_validate_json(raw_content)
        return raw_content
