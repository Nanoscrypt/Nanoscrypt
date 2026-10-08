import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from nanoscrypt.api.dependencies import get_settings
from nanoscrypt.api.schemas import SessionCreate, SessionResponse
from nanoscrypt.config.settings import Settings
from nanoscrypt.core.session_store import SessionStore
from nanoscrypt.models.session import Session

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse)
def create_session(payload: SessionCreate, cfg: Settings = Depends(get_settings)):
    """
    Create a new execution session.
    Allocates a workspace path based on the session ID.
    """
    session_id = payload.session_id or f"sess_{uuid.uuid4().hex[:8]}"
    workspace_path = f"{cfg.runtime.workspace_root}/{session_id}"

    store = SessionStore(cfg.runtime.workspace_root)
    try:
        session = store.load(session_id) or Session(
            id=session_id,
            workspace_path=workspace_path,
            created_at=datetime.now(timezone.utc),
        )
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store.save(session)

    return SessionResponse(
        id=session_id,
        workspace_path=session.workspace_path,
        created_at=session.created_at,
    )
