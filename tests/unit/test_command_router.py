import pytest
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from nanoscrypt.core.command_router import PrefixCommandRouter
from nanoscrypt.core.command_handlers import handle_todo, handle_inject, handle_confluence
from nanoscrypt.models.session import Session

class MockLLM:
    async def generate(self, prompt, system_prompt, **kwargs):
        # Return mock values based on prompt content
        if "Return ONLY a JSON block" in prompt:
            return '{"comment": "TODO: Test Injected", "line_number": 2}'
        return "# Mock Confluence Documentation\nOverview text..."

class MockPlanner:
    def __init__(self):
        self.llm = MockLLM()

class MockOrchestrator:
    def __init__(self, workspace_root):
        self.planner = MockPlanner()
        self.short_term_memory = MagicMock()
        self.context_builder = MagicMock()
        self.context_builder.workspace_root = workspace_root

@pytest.fixture
def mock_orchestrator(temp_workspace):
    return MockOrchestrator(workspace_root=temp_workspace)

def test_prefix_command_router_parsing():
    mode, payload = PrefixCommandRouter.parse("//TODO create a class")
    assert mode == "todo"
    assert payload == "create a class"

    mode, payload = PrefixCommandRouter.parse("  //inject   path/to/file.py ")
    assert mode == "inject"
    assert payload == "path/to/file.py"

    mode, payload = PrefixCommandRouter.parse("//confluence ./src")
    assert mode == "confluence"
    assert payload == "./src"

    mode, payload = PrefixCommandRouter.parse("explain how runtime works")
    assert mode == "normal"
    assert payload == "explain how runtime works"

    mode, payload = PrefixCommandRouter.parse("//foobar some text")
    assert mode == "invalid"
    assert payload == "//foobar"

@pytest.mark.asyncio
async def test_handle_todo_injection(mock_orchestrator):
    temp_dir = Path(mock_orchestrator.context_builder.workspace_root)
    test_file = temp_dir / "target.py"
    test_file.write_text("def hello():\n    print('world')\n", encoding="utf-8")

    session = Session(id="test-session-todo", workspace_path=str(temp_dir))
    payload = f"{test_file.resolve()} implement logging"

    res = await handle_todo(mock_orchestrator, payload, session)
    assert res["status"] == "completed"
    
    updated_content = test_file.read_text(encoding="utf-8")
    assert "TODO: Test Injected" in updated_content

@pytest.mark.asyncio
async def test_handle_inject_indexing(mock_orchestrator):
    temp_dir = Path(mock_orchestrator.context_builder.workspace_root)
    test_file = temp_dir / "injectable.txt"
    test_file.write_text("Secret context data", encoding="utf-8")

    session = Session(id="test-session-inject", workspace_path=str(temp_dir))
    res = await handle_inject(mock_orchestrator, str(test_file.resolve()), session)
    assert res["status"] == "completed"
    assert "Secret context data" in mock_orchestrator.short_term_memory.add.call_args[0][1]

@pytest.mark.asyncio
async def test_handle_confluence_generation(mock_orchestrator):
    temp_dir = Path(mock_orchestrator.context_builder.workspace_root)
    test_file = temp_dir / "code.py"
    test_file.write_text("class MyService:\n    pass\n", encoding="utf-8")

    session = Session(id="test-session-confluence", workspace_path=str(temp_dir))
    res = await handle_confluence(mock_orchestrator, str(test_file.resolve()), session)
    assert res["status"] == "completed"
    
    doc_path = Path("./confluence_doc.md")
    assert doc_path.exists()
    
    doc_content = doc_path.read_text(encoding="utf-8")
    assert "# Mock Confluence Documentation" in doc_content
    
    # Cleanup confluence_doc.md
    try:
        doc_path.unlink()
    except Exception:
        pass
