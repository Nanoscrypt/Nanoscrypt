import pytest
import json
from pathlib import Path
from nanoscrypt.core.runtime import RuntimeManager
from nanoscrypt.models.tool import GeneratedTool, ToolManifest

@pytest.fixture
def runtime_manager(temp_workspace):
    return RuntimeManager(workspace_root=temp_workspace / "workspaces", timeout_seconds=5)

def test_runtime_setup_and_execution(runtime_manager):
    # A simple tool adding two parameters
    code = """def run(x: int, y: int) -> int:
    return x + y
"""
    manifest = ToolManifest(name="add_tool")
    tool = GeneratedTool(
        name="add_tool",
        code=code,
        requirements=[],  # standard lib, no external dependency
        manifest=manifest,
        tests="",
        readme=""
    )

    session_id = "test-session-1"
    
    # 1. Setup workspace
    workspace = runtime_manager.setup_workspace(session_id, tool)
    assert workspace.exists()
    assert (workspace / "tool.py").exists()

    # 2. Initialize Virtual Environment
    venv_dir = runtime_manager.create_virtual_env(workspace)
    assert venv_dir.exists()

    # 3. Execute Tool
    input_data = json.dumps({"x": 10, "y": 20})
    result = runtime_manager.execute_tool(session_id, input_data)

    assert result.return_code == 0
    assert result.timed_out is False
    
    # Parse stdout response
    output_obj = json.loads(result.stdout.strip())
    assert output_obj["status"] == "success"
    assert output_obj["output"] == 30

    # 4. Cleanup
    runtime_manager.cleanup_workspace(session_id)
    assert not workspace.exists()

def test_runtime_execution_timeout(runtime_manager):
    # Tool with an infinite loop
    code = """import time
def run(seconds: int) -> str:
    time.sleep(seconds)
    return "done"
"""
    tool = GeneratedTool(
        name="infinite_tool",
        code=code,
        requirements=[],
        manifest=ToolManifest(name="infinite_tool"),
        tests="",
        readme=""
    )

    session_id = "test-session-2"
    workspace = runtime_manager.setup_workspace(session_id, tool)
    runtime_manager.create_virtual_env(workspace)

    # Trigger with 10 seconds sleep, timeout limit is 2 seconds
    result = runtime_manager.execute_tool(session_id, json.dumps({"seconds": 10}), timeout=2)

    assert result.timed_out is True
    assert result.return_code == -9  # our custom timeout status code

    runtime_manager.cleanup_workspace(session_id)
