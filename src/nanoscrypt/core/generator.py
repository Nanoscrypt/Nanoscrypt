import structlog
from typing import Any
from nanoscrypt.llm.base import LLMProvider
from nanoscrypt.llm.prompts.generator import TOOL_GENERATION_SYSTEM_PROMPT, TOOL_GENERATION_USER_TEMPLATE
from nanoscrypt.models.tool import GeneratedTool
from nanoscrypt.models.plan import PlannerDecision

logger = structlog.get_logger()

class ToolGenerator:
    """Invokes the LLM to synthesize a complete tool package (code, tests, readme, manifest, requirements)."""

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    async def generate(self, decision: PlannerDecision, **kwargs: Any) -> GeneratedTool:
        """Takes a PlannerDecision specification and returns a fully synthesized GeneratedTool package."""
        log = logger.bind(
            component="tool_generator",
            tool_name=decision.tool_name
        )
        log.info("tool_generation_started", purpose=decision.tool_purpose)

        # Build user prompt
        user_prompt = TOOL_GENERATION_USER_TEMPLATE.format(
            tool_name=decision.tool_name or "unnamed_tool",
            tool_purpose=decision.tool_purpose or "no purpose specified",
            input_description=decision.input_description or "any",
            output_description=decision.output_description or "any",
            dependencies_hint=", ".join(decision.dependencies_hint) if decision.dependencies_hint else "none"
        )

        try:
            # We call the structured generation using the GeneratedTool model
            generated_tool = await self.llm.generate_structured(
                prompt=user_prompt,
                response_model=GeneratedTool,
                system_prompt=TOOL_GENERATION_SYSTEM_PROMPT,
                **kwargs
            )
            
            # Ensure name matches specification
            if decision.tool_name and not generated_tool.name:
                generated_tool.name = decision.tool_name
                
            log.info(
                "tool_generation_completed",
                lines_of_code=len(generated_tool.code.splitlines()),
                requirements_count=len(generated_tool.requirements)
            )
            return generated_tool
        except Exception as e:
            log.error("tool_generation_failed", error=str(e))
            raise
