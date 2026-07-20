from enum import Enum

from pydantic import BaseModel


class PermissionLevel(str, Enum):
    DENY = "deny"
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    ADMIN = "admin"


class AgentPermissions(BaseModel):
    file_system: PermissionLevel = PermissionLevel.DENY
    network: PermissionLevel = PermissionLevel.DENY
    tool_generation: PermissionLevel = PermissionLevel.EXECUTE
    tool_execution: PermissionLevel = PermissionLevel.EXECUTE
    delegation: bool = False
