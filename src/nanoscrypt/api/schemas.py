from datetime import datetime
from pydantic import BaseModel, Field

class SessionCreate(BaseModel):
    session_id: str | None = None

class SessionResponse(BaseModel):
    id: str
    workspace_path: str
    created_at: datetime

class TaskSubmit(BaseModel):
    prompt: str

class TaskResponse(BaseModel):
    status: str
    action_taken: str
    tool_name: str | None = None
    version: int | None = None
    output: str | None = None
    error: str | None = None
    runtime_ms: int | None = None

class ToolResponse(BaseModel):
    name: str
    purpose: str
    language: str
    current_version: int
    success_rate: float
    usage_count: int
    status: str
    created_at: datetime
