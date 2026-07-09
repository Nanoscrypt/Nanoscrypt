import structlog
from typing import Any
from nanoscrypt.llm.base import LLMProvider
from nanoscrypt.llm.prompts.planner import PLANNER_SYSTEM_PROMPT
from nanoscrypt.models.plan import PlannerDecision

logger = structlog.get_logger()

class Planner:
    """Core Planner component that decides whether to generate a tool, reuse a tool, or answer directly."""

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    async def decide(self, assembled_context: str, **kwargs: Any) -> PlannerDecision:
        """Sends the contextual prompt to the LLM and returns a structured PlannerDecision."""
        log = logger.bind(component="planner")
        log.debug("planner_planning_started")

        try:
            decision = await self.llm.generate_structured(
                prompt=assembled_context,
                response_model=PlannerDecision,
                system_prompt=PLANNER_SYSTEM_PROMPT,
                **kwargs
            )
            log.info("planner_planning_completed", action=decision.action, tool_name=decision.tool_name)
            return decision
        except Exception as e:
            log.error("planner_planning_failed", error=str(e))
            raise
