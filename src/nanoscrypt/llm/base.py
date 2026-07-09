from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class LLMProvider(Protocol):
    """Protocol defining the core interface for interacting with Large Language Models."""
    
    async def generate(self, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> str:
        """Sends a prompt to the LLM and returns the text response."""
        ...
        
    async def generate_structured(
        self, 
        prompt: str, 
        response_model: Any, 
        system_prompt: str | None = None, 
        **kwargs: Any
    ) -> Any:
        """Sends a prompt to the LLM and returns parsed structured data matching response_model."""
        ...
