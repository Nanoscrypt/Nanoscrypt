from datetime import UTC, datetime

from pydantic import BaseModel, Field


class SessionToolOutput(BaseModel):
    tool_name: str
    version: int
    success: bool
    input_data: dict[str, str]
    output_data: str | None = None
    error: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Session(BaseModel):
    id: str
    workspace_path: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    active_prompt: str | None = None
    active_agent: str | None = None  # Tracks the active agent executing tasks
    history: list[SessionToolOutput] = Field(default_factory=list)
