import pytest
from typing import Any
from nanoscrypt.core.planner import Planner
from nanoscrypt.models.plan import PlannerDecision
from nanoscrypt.llm.base import LLMProvider

class DummyLLMProvider(LLMProvider):
    """Stub LLM provider that returns static structures for testing."""
    
    def __init__(self, expected_decision: PlannerDecision):
        self.expected_decision = expected_decision
        self.prompt_received = None
        self.system_received = None

    async def generate(self, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> str:
        return ""

    async def generate_structured(
        self, 
        prompt: str, 
        response_model: Any, 
        system_prompt: str | None = None, 
        **kwargs: Any
    ) -> Any:
        self.prompt_received = prompt
        self.system_received = system_prompt
        return self.expected_decision

@pytest.mark.asyncio
async def test_planner_decide():
    expected = PlannerDecision(
        action="generate_tool",
        tool_name="csv_analyzer",
        tool_purpose="Read and count csv rows",
        input_description="Filepath of csv",
        output_description="Count details",
        dependencies_hint=["pandas"],
        reasoning="Need custom script to parse inputs"
    )
    
    dummy_llm = DummyLLMProvider(expected)
    planner = Planner(llm=dummy_llm)
    
    decision = await planner.decide(assembled_context="Task: Parse values")
    
    assert decision.action == "generate_tool"
    assert decision.tool_name == "csv_analyzer"
    assert dummy_llm.prompt_received == "Task: Parse values"
    assert "orchestrator core" in dummy_llm.system_received
