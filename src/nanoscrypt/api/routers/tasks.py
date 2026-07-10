from fastapi import APIRouter, Depends, HTTPException, Query

from nanoscrypt.api.dependencies import get_orchestrator
from nanoscrypt.api.schemas import TaskResponse, TaskSubmit
from nanoscrypt.core.orchestrator import Orchestrator
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
    # Initialize ephemeral session tracking
    session = Session(id=session_id, workspace_path=f"./workspaces/{session_id}")

    try:
        result = await orchestrator.execute_task(
            user_prompt=payload.prompt, session=session
        )

        # Map execution outcome to target HTTP response format
        return TaskResponse(
            status=result.get("status", "error"),
            action_taken=result.get("action_taken", "none"),
            tool_name=result.get("tool_name"),
            version=result.get("version"),
            output=result.get("output") or result.get("response"),
            error=result.get("error") or result.get("message"),
            runtime_ms=result.get("runtime_ms"),
        )
    except Exception as e:
        import logging

        logging.error(f"Task execution failed inside engine: {e!s}")
        raise HTTPException(
            status_code=500, detail="An internal error occurred during task execution."
        )
