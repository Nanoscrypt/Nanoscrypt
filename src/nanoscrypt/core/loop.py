import asyncio
from typing import AsyncIterator, Any
from nanoscrypt.core.events import (
    AgentStartEvent,
    AgentEndEvent,
    TurnStartEvent,
    TurnEndEvent,
    ThinkingDeltaEvent,
    MessageStartEvent,
    MessageDeltaEvent,
    MessageEndEvent,
    ToolExecutionStartEvent,
    ToolExecutionEndEvent
)

async def run_agent_loop(
    orchestrator: Any,
    user_prompt: str,
    session: Any,
    agent: Any = None,
    signal: Any = None,
    harness: Any = None,
) -> AsyncIterator[Any]:
    """Asynchronous agent execution loop yielding granular progress events."""
    yield AgentStartEvent()
    yield TurnStartEvent(turn=1)
    
    yield ThinkingDeltaEvent(delta="Thinking...")
    
    if signal and signal.is_cancelled():
        yield AgentEndEvent()
        return
        
    result = await orchestrator.execute_task(
        user_prompt=user_prompt,
        session=session,
        agent=agent
    )
    if harness is not None:
        harness.last_result = result

    # Emit LLM reasoning / thinking details
    reasoning = result.get("reasoning")
    if reasoning:
        yield ThinkingDeltaEvent(delta=f"\n[Reasoning]: {reasoning}")
    elif result.get("response"):
        yield ThinkingDeltaEvent(delta=f"\n[Planning]: {result.get('response')}")
    
    if result.get("action_taken") == "execute_tool":
        yield ToolExecutionStartEvent(
            tool_name=result.get("tool_name", "unknown"),
            arguments={"query": user_prompt}
        )
        yield ToolExecutionEndEvent(
            tool_name=result.get("tool_name", "unknown"),
            success=result.get("status") == "completed",
            output=result.get("output"),
            error=result.get("error")
        )
        
    yield MessageStartEvent(message_role="assistant")
    
    output_content = str(result.get("output") or result.get("response") or "")
    
    # Typewriter streaming simulation for smooth token rendering
    chunk_size = 5
    for i in range(0, len(output_content), chunk_size):
        if signal and signal.is_cancelled():
            break
        chunk = output_content[i:i+chunk_size]
        yield MessageDeltaEvent(delta=chunk)
        await asyncio.sleep(0.01)
        
    yield MessageEndEvent(message={"role": "assistant", "content": output_content})
    yield TurnEndEvent(turn=1)
    yield AgentEndEvent()
