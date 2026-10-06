import pytest
import json
from nanoscrypt.core.repair import RepairLoop
from nanoscrypt.core.runtime import RuntimeManager, ExecutionResult
from nanoscrypt.core.validator import ToolValidator
from nanoscrypt.models.tool import GeneratedTool, ToolManifest
from nanoscrypt.llm.base import LLMProvider

class MockRepairLLM(LLMProvider):
    def __init__(self, repaired_tool: GeneratedTool) -> None:
        self.repaired_tool = repaired_tool
        self.calls = 0

    async def generate(self, prompt: str, system_prompt: str | None = None, **kwargs) -> str:
        return ""

    async def generate_structured(self, prompt: str, response_model, system_prompt = None, **kwargs):
        self.calls += 1
        return self.repaired_tool

@pytest.mark.asyncio
async def test_repair_loop_fixes_bug(temp_workspace):
    # 1. Setup a broken tool with a buggy divide function
    broken_code = """def run(x: int, y: int) -> float:
    # BUG: division by zero is not handled
    return x / y
"""
    
    # We write a unit test inside tests.py that checks division by zero
    tests_code = """import unittest
import tool

class TestTool(unittest.TestCase):
    def test_divide_by_zero(self):
        # This will fail on the broken code because it raises ZeroDivisionError
        try:
            res = tool.run(10, 0)
            self.assertEqual(res, 0.0)
        except ZeroDivisionError:
            self.fail("ZeroDivisionError raised")
"""

    broken_tool = GeneratedTool(
        name="divide_tool",
        code=broken_code,
        requirements=[],
        manifest=ToolManifest(name="divide_tool"),
        tests=tests_code,
        readme=""
    )

    # 2. Setup the repaired tool version
    repaired_code = """def run(x: int, y: int) -> float:
    if y == 0:
        return 0.0
    return x / y
"""
    
    repaired_tool = GeneratedTool(
        name="divide_tool",
        code=repaired_code,
        requirements=[],
        manifest=ToolManifest(name="divide_tool"),
        tests=tests_code,
        readme=""
    )

    mock_llm = MockRepairLLM(repaired_tool)
    validator = ToolValidator()
    runtime_manager = RuntimeManager(workspace_root=temp_workspace / "workspaces", timeout_seconds=5)

    repair_loop = RepairLoop(
        llm=mock_llm,
        validator=validator,
        runtime_manager=runtime_manager,
        max_attempts=2
    )

    session_id = "repair-test-session"
    workspace = runtime_manager.setup_workspace(session_id, broken_tool)
    runtime_manager.create_virtual_env(workspace)

    # 3. First, run the broken tool's tests. They must FAIL
    initial_test_res = repair_loop.run_tests_in_sandbox(session_id, broken_tool)
    assert initial_test_res.return_code != 0

    # 4. Trigger Repair Loop
    fixed_tool, attempts = await repair_loop.repair_tool(
        session_id=session_id,
        tool=broken_tool,
        failure_result=initial_test_res,
        tool_purpose="division utility"
    )

    assert fixed_tool is not None
    assert attempts == 1
    assert "if y == 0:" in fixed_tool.code
    
    # Confirm running tests on fixed_tool returns success
    final_test_res = repair_loop.run_tests_in_sandbox(session_id, fixed_tool)
    assert final_test_res.return_code == 0

    runtime_manager.cleanup_workspace(session_id)


class MockMultiRepairLLM(LLMProvider):
    def __init__(self, tools: list[GeneratedTool]) -> None:
        self.tools = tools
        self.calls = 0

    async def generate(self, prompt: str, system_prompt: str | None = None, **kwargs) -> str:
        return ""

    async def generate_structured(self, prompt: str, response_model, system_prompt = None, **kwargs):
        idx = min(self.calls, len(self.tools) - 1)
        tool = self.tools[idx]
        self.calls += 1
        return tool


@pytest.mark.asyncio
async def test_repair_loop_saves_attempts_with_lineage(temp_workspace):
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select
    from nanoscrypt.models.database import Base, DBRepairAttempt

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # 1. Broken tool
    broken_code = """def run(x: int, y: int) -> float:
    return x / y
"""
    tests_code = """import unittest
import tool

class TestTool(unittest.TestCase):
    def test_divide_by_zero(self):
        try:
            res = tool.run(10, 0)
            self.assertEqual(res, 0.0)
        except ZeroDivisionError:
            self.fail("ZeroDivisionError raised")
"""
    broken_tool = GeneratedTool(
        name="calc_tool",
        code=broken_code,
        requirements=[],
        manifest=ToolManifest(name="calc_tool"),
        tests=tests_code,
        readme=""
    )

    # Attempt 1 returns still broken code
    still_broken_code = """def run(x: int, y: int) -> float:
    # still wrong
    return x / (y + 0)
"""
    attempt1_tool = GeneratedTool(
        name="calc_tool",
        code=still_broken_code,
        requirements=[],
        manifest=ToolManifest(name="calc_tool"),
        tests=tests_code,
        readme=""
    )

    # Attempt 2 returns working code
    fixed_code = """def run(x: int, y: int) -> float:
    if y == 0:
        return 0.0
    return x / y
"""
    attempt2_tool = GeneratedTool(
        name="calc_tool",
        code=fixed_code,
        requirements=[],
        manifest=ToolManifest(name="calc_tool"),
        tests=tests_code,
        readme=""
    )

    mock_llm = MockMultiRepairLLM([attempt1_tool, attempt2_tool])
    validator = ToolValidator()
    runtime_manager = RuntimeManager(workspace_root=temp_workspace / "workspaces", timeout_seconds=5)

    repair_loop = RepairLoop(
        llm=mock_llm,
        validator=validator,
        runtime_manager=runtime_manager,
        max_attempts=3,
        session_factory=session_factory,
    )

    session_id = "test-lineage-session"
    workspace = runtime_manager.setup_workspace(session_id, broken_tool)
    runtime_manager.create_virtual_env(workspace)

    initial_test_res = repair_loop.run_tests_in_sandbox(session_id, broken_tool)
    assert initial_test_res.return_code != 0

    repaired_tool, attempts = await repair_loop.repair_tool(
        session_id=session_id,
        tool=broken_tool,
        failure_result=initial_test_res,
        tool_purpose="division utility"
    )

    assert repaired_tool is not None
    assert attempts == 2

    # Query the saved repair attempts from the database
    async with session_factory() as session:
        result = await session.execute(
            select(DBRepairAttempt).order_by(DBRepairAttempt.attempt_number)
        )
        saved_attempts = result.scalars().all()

    assert len(saved_attempts) == 2
    att1, att2 = saved_attempts[0], saved_attempts[1]

    # Verify attempt 1 details
    assert att1.attempt_number == 1
    assert att1.tool_name == "calc_tool"
    assert att1.parent_repair_id is None
    assert "still wrong" in att1.generated_code  # Full uncompressed code preserved
    assert att1.return_code != 0

    # Verify attempt 2 details and the lineage link
    assert att2.attempt_number == 2
    assert att2.tool_name == "calc_tool"
    assert att2.parent_repair_id == att1.id  # "this repair came from that repair" link
    assert "if y == 0:" in att2.generated_code  # Full uncompressed code preserved
    assert att2.return_code == 0

    runtime_manager.cleanup_workspace(session_id)

