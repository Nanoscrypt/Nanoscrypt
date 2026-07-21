import pytest
from unittest.mock import AsyncMock, MagicMock
from nanoscrypt.core.harness import AgentHarness
from nanoscrypt.core.events import (
    AgentStartEvent,
    AgentEndEvent,
    TurnStartEvent,
    TurnEndEvent,
    ThinkingDeltaEvent,
    MessageStartEvent,
    MessageDeltaEvent,
    MessageEndEvent
)
from nanoscrypt.models.session import Session

@pytest.mark.asyncio
async def test_harness_initialization():
    orchestrator = MagicMock()
    session = Session(id="test_session", workspace_path="./test_workspace")
    harness = AgentHarness(orchestrator, session)
    
    assert harness.session == session
    assert not harness.is_running
    assert harness.last_result is None

@pytest.mark.asyncio
async def test_harness_queues():
    orchestrator = MagicMock()
    session = Session(id="test_session", workspace_path="./test_workspace")
    harness = AgentHarness(orchestrator, session)
    
    harness.steer("Do step A")
    harness.follow_up("Do step B")
    
    state = harness.queue_update_event()
    assert state.steering == ("Do step A",)
    assert state.follow_up == ("Do step B",)
    
    harness.clear_queues()
    state_empty = harness.queue_update_event()
    assert len(state_empty.steering) == 0
    assert len(state_empty.follow_up) == 0

@pytest.mark.asyncio
async def test_harness_prompt_execution():
    orchestrator = MagicMock()
    mock_result = {"status": "completed", "output": "Hello Balaji"}
    orchestrator.execute_task = AsyncMock(return_value=mock_result)
    
    session = Session(id="test_session", workspace_path="./test_workspace")
    harness = AgentHarness(orchestrator, session)
    
    events_received = []
    def listener(event):
        events_received.append(event)
        
    harness.subscribe(listener)
    
    # Run the prompt loop
    async for event in harness.prompt("Hello"):
        pass
        
    assert harness.last_result == mock_result
    
    types = [e.type for e in events_received]
    assert "agent_start" in types
    assert "turn_start" in types
    assert "thinking_delta" in types
    assert "message_start" in types
    assert "message_delta" in types
    assert "message_end" in types
    assert "turn_end" in types
    assert "agent_end" in types
