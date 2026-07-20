from enum import Enum

from pydantic import BaseModel, Field

from nanoscrypt.models.permissions import AgentPermissions


class AgentRole(str, Enum):
    PLANNER = "planner"
    CODER = "coder"
    REVIEWER = "reviewer"
    EXECUTOR = "executor"
    RESEARCHER = "researcher"
    CUSTOM = "custom"


class Agent(BaseModel):
    name: str
    role: AgentRole
    goal: str
    backstory: str = ""
    tools: list[str] = Field(default_factory=list)  # Allowed tools list
    max_iterations: int = 10
    allow_delegation: bool = False
    allow_web_access: bool = False
    verbose: bool = False
    permissions: AgentPermissions = Field(default_factory=AgentPermissions)
