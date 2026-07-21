import pytest
import json
from pathlib import Path
from nanoscrypt.core.context import ContextBuilder
from nanoscrypt.core.planner import Planner
from nanoscrypt.core.generator import ToolGenerator
from nanoscrypt.core.validator import ToolValidator
from nanoscrypt.core.runtime import RuntimeManager
from nanoscrypt.core.registry import ToolRegistry
from nanoscrypt.core.versioning import VersionManager
from nanoscrypt.core.orchestrator import Orchestrator
from nanoscrypt.models.session import Session
from nanoscrypt.models.plan import PlannerDecision
from nanoscrypt.models.tool import GeneratedTool, ToolManifest
from nanoscrypt.llm.base import LLMProvider

class MockFullLLMProvider(LLMProvider):
    def __init__(self) -> None:
        self.planner_decision = None
        self.generated_tool = None
        self.planner_calls = 0
        self.generator_calls = 0

    async def generate(self, prompt: str, system_prompt: str | None = None, **kwargs) -> str:
        return ""

    async def generate_structured(self, prompt: str, response_model, system_prompt = None, **kwargs):
        if response_model.__name__ == "PlannerDecision":
            self.planner_calls += 1
            return self.planner_decision
        elif response_model.__name__ == "GeneratedTool":
            self.generator_calls += 1
            return self.generated_tool
        raise ValueError("Unknown response model requested in mock")

@pytest.mark.asyncio
async def test_full_lifecycle_and_tool_reuse(temp_workspace):
    # 1. Instantiate modules
    mock_llm = MockFullLLMProvider()
    
    context_builder = ContextBuilder(workspace_root=temp_workspace)
    planner = Planner(llm=mock_llm)
    generator = ToolGenerator(llm=mock_llm)
    validator = ToolValidator()
    
    runtime_manager = RuntimeManager(workspace_root=temp_workspace / "workspaces", timeout_seconds=5)
    registry = ToolRegistry(database_url="sqlite+aiosqlite:///:memory:")
    version_manager = VersionManager(tools_dir=temp_workspace / "generated_tools")

    await registry.initialize_db()

    orchestrator = Orchestrator(
        context_builder=context_builder,
        planner=planner,
        generator=generator,
        validator=validator,
        runtime_manager=runtime_manager,
        registry=registry,
        version_manager=version_manager
    )

    # 2. Setup mock tool generation spec
    tool_name = "math_square"
    mock_llm.planner_decision = PlannerDecision(
        action="generate_tool",
        tool_name=tool_name,
        tool_purpose="calculate square of a number",
        input_description="JSON dictionary with key val",
        output_description="Integer squared",
        dependencies_hint=[],
        reasoning="Need square calculation tool"
    )

    manifest = ToolManifest(
        name=tool_name,
        input_schema={"val": "int"},
        output_schema={"squared": "int"}
    )
    
    mock_llm.generated_tool = GeneratedTool(
        name=tool_name,
        code="def run(val: int) -> int:\n    return val * val\n",
        requirements=[],
        manifest=manifest,
        tests="pass",
        readme="# Square Tool"
    )

    session = Session(
        id="session-full-1",
        workspace_path=str(temp_workspace)
    )

    # 3. Run execution 1 (Should trigger Tool Generation + Save + Execute)
    user_input = json.dumps({"val": 5})
    res = await orchestrator.execute_task(
        user_prompt=user_input,
        session=session
    )

    assert res["status"] == "completed"
    assert res["tool_name"] == tool_name
    assert res["version"] == 1
    assert res["output"] == "25"
    assert mock_llm.generator_calls == 1

    # Check that tool is registered and saved on disk
    db_tool = await registry.get(tool_name)
    assert db_tool is not None
    assert db_tool.current_version == 1

    # 4. Trigger Run 2 (Alter Planner to "reuse_tool" matching our registry)
    mock_llm.planner_decision = PlannerDecision(
        action="reuse_tool",
        tool_name=tool_name,
        tool_purpose="reuse square calculation",
        input_description="JSON dictionary with key val",
        output_description="Integer squared",
        dependencies_hint=[],
        reuse_existing=True,
        reasoning="Reuse existing square tool"
    )

    session2 = Session(
        id="session-full-2",
        workspace_path=str(temp_workspace)
    )

    # Run execution 2 (Should reuse the tool without triggering Generator)
    user_input2 = json.dumps({"val": 9})
    res2 = await orchestrator.execute_task(
        user_prompt=user_input2,
        session=session2
    )

    assert res2["status"] == "completed"
    assert res2["tool_name"] == tool_name
    assert res2["version"] == 1
    assert res2["output"] == "81"
    
    # Confirm generator was NOT called again during reuse
    assert mock_llm.generator_calls == 1
