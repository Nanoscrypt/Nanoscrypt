from fastapi import APIRouter, Depends, HTTPException, Query

from nanoscrypt.api.dependencies import get_orchestrator
from nanoscrypt.api.schemas import TaskResponse, TaskSubmit
from nanoscrypt.core.harness import AgentHarness
from nanoscrypt.core.orchestrator import Orchestrator
from nanoscrypt.core.session_store import SessionStore
from nanoscrypt.models.session import Session

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskResponse)
async def submit_task(
    payload: TaskSubmit,
    session_id: str = Query(
        ..., description="Active session ID to bound the execution workspace"
    ),
    orchestrator: Orchestrator = Depends(get_orchestrator),
):
    """
    Submit a task to be executed by the orchestrator.
    Requires a session_id to bound the execution workspace.
    """
    store = SessionStore(orchestrator.runtime_manager.workspace_root)
    try:
        session = store.load(session_id) or Session(
            id=session_id,
            workspace_path=str(
                orchestrator.runtime_manager.workspace_root / session_id
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        harness = AgentHarness(orchestrator, session, session_store=store)
        async for _ in harness.prompt(payload.prompt):
            pass
        result = harness.last_result or {"status": "cancelled"}

        # Map execution outcome to target HTTP response format
        return TaskResponse(
            status=result.get("status", "error"),
            action_taken=result.get("action_taken", "none"),
            tool_name=result.get("tool_name"),
            version=result.get("version"),
            output=result.get("output") or result.get("response"),
            error=result.get("error") or result.get("message"),
            runtime_ms=result.get("runtime_ms"),
            execution_id=result.get("execution_id"),
        )
    except Exception as e:
        import logging

        logging.error(f"Task execution failed inside engine: {e!s}")
        raise HTTPException(
            status_code=500, detail="An internal error occurred during task execution."
        )
