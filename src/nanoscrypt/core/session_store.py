"""Small, local persistence layer for resumable Nanoscrypt sessions."""

import re
import tempfile
from pathlib import Path

from nanoscrypt.models.session import Session

_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,96}$")


class SessionStore:
    """Persist session state as JSON beneath a configured workspace root."""

    def __init__(self, workspace_root: str | Path) -> None:
        self.root = Path(workspace_root).resolve()
        self.directory = self.root / ".nanoscrypt_sessions"

    def _path_for(self, session_id: str) -> Path:
        if not _SESSION_ID.fullmatch(session_id):
            raise ValueError(
                "Session ID must contain only letters, numbers, underscores, or hyphens."
            )
        resolved_directory = self.directory.resolve()
        if resolved_directory.parent != self.root:
            raise ValueError("Session storage directory must remain under the workspace root.")
        path = (resolved_directory / f"{session_id}.json").resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("Session path is outside the configured workspace.") from exc
        return path

    def load(self, session_id: str) -> Session | None:
        path = self._path_for(session_id)
        if not path.is_file():
            return None
        session = Session.model_validate_json(path.read_text(encoding="utf-8"))
        if session.id != session_id:
            raise ValueError("Persisted session ID does not match its storage key.")
        return session

    def save(self, session: Session) -> None:
        path = self._path_for(session.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = session.model_dump_json(indent=2)
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f"{session.id}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_name = temp_file.name
                temp_file.write(content)
                temp_file.flush()
            Path(temp_name).replace(path)
        finally:
            if temp_name:
                Path(temp_name).unlink(missing_ok=True)
