import pytest
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from nanoscrypt.core.code_agent import CodeAgentExecutor
from nanoscrypt.models.session import Session
from nanoscrypt.models.agent import Agent, AgentRole
from nanoscrypt.core.runtime import RuntimeManager

class MockLLM:
    def __init__(self):
        self.generate_calls = []
        self.responses = []

    async def generate(self, prompt, system_prompt, **kwargs):
        self.generate_calls.append(prompt)
        if self.responses:
            return self.responses.pop(0)
        return '{"thought": "done", "code": "final_answer(\\"ok\\")"}'

class MockPlanner:
    def __init__(self):
        self.llm = MockLLM()

class MockRegistry:
    def __init__(self):
        self.tools = {}

    async def search(self, q):
        return list(self.tools.values())

    async def get(self, name):
        return self.tools.get(name)

class MockOrchestrator:
    def __init__(self, workspace_root):
        self.planner = MockPlanner()
        self.registry = MockRegistry()
        self.runtime_manager = RuntimeManager(workspace_root=workspace_root)

@pytest.fixture
def mock_orchestrator(temp_workspace):
    return MockOrchestrator(workspace_root=temp_workspace / "workspaces")

@pytest.mark.asyncio
async def test_code_agent_simple_execution(mock_orchestrator):
    executor = CodeAgentExecutor(mock_orchestrator)
    session = Session(id="test-session-code-agent-1", workspace_path=str(mock_orchestrator.runtime_manager.workspace_root / "test-session-code-agent-1"))

    # Test basic arithmetic code execution inside the helper loop
    obs, final_val, term = await executor._run_sandbox_code(
        code="print(5 + 15)",
        session=session,
        state_file_content=[]
    )

    assert term is False
    assert final_val is None
    assert "20" in obs

    # Test termination via final_answer()
    obs, final_val, term = await executor._run_sandbox_code(
        code="final_answer('hello-world')",
        session=session,
        state_file_content=[]
    )

    assert term is True
    assert final_val == "hello-world"

    mock_orchestrator.runtime_manager.cleanup_workspace(session.id)

@pytest.mark.asyncio
async def test_code_agent_tool_rpc_call(mock_orchestrator):
    from nanoscrypt.models.tool import GeneratedTool, ToolManifest
    
    # 1. Register a mock tool in registry
    mock_tool = GeneratedTool(
        name="square_number",
        code="def run(num: int) -> int:\n    return num * num\n",
        requirements=[],
        manifest=ToolManifest(name="square_number", input_schema={"num": "int"}),
        tests="",
        readme=""
    )
    mock_orchestrator.registry.tools["square_number"] = mock_tool

    executor = CodeAgentExecutor(mock_orchestrator)
    session = Session(id="test-session-code-agent-2", workspace_path=str(mock_orchestrator.runtime_manager.workspace_root / "test-session-code-agent-2"))

    # Verify that helper_tools contains square_number, and tool execution works
    obs, final_val, term = await executor._run_sandbox_code(
        code="res = square_number(num=6)\nprint(f'Squared result: {res}')",
        session=session,
        state_file_content=[]
    )

    assert "Squared result: 36" in obs
    mock_orchestrator.runtime_manager.cleanup_workspace(session.id)
