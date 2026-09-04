import structlog
from typing import Any

from nanoscrypt.core.postprocessor import CodePostProcessor
from nanoscrypt.llm.base import LLMProvider
from nanoscrypt.llm.prompts.evolution import (
    TOOL_EVOLUTION_SYSTEM_PROMPT,
    TOOL_EVOLUTION_USER_TEMPLATE,
)
from nanoscrypt.models.tool import GeneratedTool

logger = structlog.get_logger()


class ToolMutator:
    """Performs AST-guided incremental code evolution on existing verified tools,
    maintaining backwards-compatibility while adding new capabilities."""

    def __init__(self, llm: LLMProvider):
        self.llm = llm
        self.post_processor = CodePostProcessor()

    async def evolve(
        self,
        base_tool: GeneratedTool,
        base_version: int,
        user_prompt: str,
        mutation_goals: list[str] | None = None,
    ) -> GeneratedTool:
        """Takes a base GeneratedTool and synthesizes an evolved GeneratedTool version."""
        log = logger.bind(component="tool_mutator", tool_name=base_tool.name, base_version=base_version)
        log.info("tool_mutator_evolution_started")

        goals_str = "\n".join(f"- {g}" for g in (mutation_goals or [user_prompt]))
        manifest_str = (
            base_tool.manifest.model_dump_json(indent=2)
            if hasattr(base_tool.manifest, "model_dump_json")
            else str(base_tool.manifest)
        )
        reqs_str = "\n".join(base_tool.requirements) if base_tool.requirements else "None"

        purpose = getattr(base_tool, "purpose", None) or (base_tool.readme[:200] if getattr(base_tool, "readme", None) else base_tool.name)

        user_content = TOOL_EVOLUTION_USER_TEMPLATE.format(
            tool_name=base_tool.name,
            base_version=base_version,
            tool_purpose=purpose,
            user_prompt=user_prompt,
            mutation_goals=goals_str,
            base_code=base_tool.code,
            base_manifest=manifest_str,
            base_requirements=reqs_str,
            base_tests=base_tool.tests,
        )

        evolved_tool = await self.llm.generate_structured(
            prompt=user_content,
            response_model=GeneratedTool,
            system_prompt=TOOL_EVOLUTION_SYSTEM_PROMPT,
        )

        # Run automated post-processing cleanup (imports, missing dependencies, encoding)
        evolved_tool = self.post_processor.process(evolved_tool)

        log.info(
            "tool_mutator_evolution_completed",
            new_params=list(evolved_tool.manifest.input_schema.keys()) if evolved_tool.manifest else [],
        )
        return evolved_tool
