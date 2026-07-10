import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends

from nanoscrypt.api.dependencies import get_settings
from nanoscrypt.api.schemas import SessionCreate, SessionResponse
from nanoscrypt.config.settings import Settings

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse)
def create_session(payload: SessionCreate, cfg: Settings = Depends(get_settings)):
    """
    Create a new execution session.
    Allocates a workspace path based on the session ID.
    """
    session_id = payload.session_id or f"sess_{uuid.uuid4().hex[:8]}"
    workspace_path = f"{cfg.runtime.workspace_root}/{session_id}"

    return SessionResponse(
        id=session_id, workspace_path=workspace_path, created_at=datetime.now(UTC)
    )
