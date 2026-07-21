import pytest
from fastapi.testclient import TestClient
from nanoscrypt.api.app import app
from nanoscrypt.api.dependencies import get_orchestrator, get_registry
from nanoscrypt.models.plan import PlannerDecision
from nanoscrypt.models.tool import GeneratedTool, ToolManifest
from nanoscrypt.core.orchestrator import Orchestrator
from nanoscrypt.core.registry import ToolRegistry

# Mock Orchestrator for API testing
class MockOrchestrator:
    async def execute_task(self, user_prompt: str, session):
        return {
            "status": "completed",
            "action_taken": "execute_tool",
            "tool_name": "math_square",
            "version": 1,
            "output": "25",
            "runtime_ms": 120
        }

@pytest.fixture
def api_client():
    # Override orchestrator to prevent real LLM calls during endpoint checks
    app.dependency_overrides[get_orchestrator] = lambda: MockOrchestrator()
    yield TestClient(app)
    app.dependency_overrides.clear()

def test_health_endpoint(api_client):
    response = api_client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "nanoscrypt-api"}

def test_session_create(api_client):
    response = api_client.post("/api/v1/sessions", json={"session_id": "test-session"})
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "test-session"
    assert "workspace_path" in data

def test_task_submit(api_client):
    response = api_client.post(
        "/api/v1/tasks?session_id=test-session",
        json={"prompt": "calculate square of 5"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["tool_name"] == "math_square"
    assert data["output"] == "25"

@pytest.mark.asyncio
async def test_tools_list_endpoint(temp_workspace):
    # Setup temporary database registry inside router override
    registry = ToolRegistry("sqlite+aiosqlite:///:memory:")
    await registry.initialize_db()

    # Seed tool
    manifest = ToolManifest(name="xml_converter")
    tool = GeneratedTool(
        name="xml_converter", code="def run(): pass", requirements=[],
        manifest=manifest, tests="", readme="Convert XML"
    )
    await registry.register(tool, "sha", "prompt")

    app.dependency_overrides[get_registry] = lambda: registry
    client = TestClient(app)

    # Test list endpoint
    response = client.get("/api/v1/tools")
    assert response.status_code == 200
    tools_list = response.json()
    assert len(tools_list) == 1
    assert tools_list[0]["name"] == "xml_converter"

    # Test detail endpoint
    response_detail = client.get("/api/v1/tools/xml_converter")
    assert response_detail.status_code == 200
    assert response_detail.json()["name"] == "xml_converter"

    app.dependency_overrides.clear()
