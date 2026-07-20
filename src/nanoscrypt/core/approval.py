import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from nanoscrypt.config.settings import settings


class ApprovalType(str, Enum):
    TOOL_GENERATION = "tool_generation"
    TOOL_EXECUTION = "tool_execution"
    WEB_ACCESS = "web_access"
    FILE_ACCESS = "file_access"
    HIGH_RISK_OPERATION = "high_risk"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


class ApprovalRequest(BaseModel):
    id: str = Field(default_factory=lambda: f"req_{uuid.uuid4().hex[:8]}")
    session_id: str
    approval_type: ApprovalType
    description: str
    risk_level: str  # low, medium, high, critical
    resource_details: dict[str, Any] = Field(default_factory=dict)
    agent_name: str = "orchestrator"
    status: ApprovalStatus = ApprovalStatus.PENDING
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: datetime | None = None
    reason: str | None = None


class ApprovalGate:
    """Manages human-in-the-loop workflows for sensitive actions."""

    def __init__(
        self, approval_callback: Callable[[ApprovalRequest], bool] | None = None
    ):
        self.approval_callback = approval_callback
        self.pending_requests: dict[str, ApprovalRequest] = {}
        self.history: list[ApprovalRequest] = []

    def should_require_approval(
        self, approval_type: ApprovalType, risk_level: str
    ) -> bool:
        """Determines if the operation needs human-in-the-loop validation based on settings."""
        mode = settings.security.approval_mode
        if mode == "auto":
            return False

        # Risk levels mapping for comparison
        risk_map = {"low": 1, "medium": 2, "high": 3, "critical": 4}
        threshold = risk_map.get(settings.security.default_risk_threshold.lower(), 2)
        current = risk_map.get(risk_level.lower(), 2)

        return current >= threshold

    async def request_approval(
        self,
        session_id: str,
        approval_type: ApprovalType,
        description: str,
        risk_level: str,
        resource_details: dict[str, Any],
        agent_name: str = "orchestrator",
    ) -> bool:
        """Creates a pending request and waits for resolution (via callback, polling, or CLI)."""
        req = ApprovalRequest(
            session_id=session_id,
            approval_type=approval_type,
            description=description,
            risk_level=risk_level,
            resource_details=resource_details,
            agent_name=agent_name,
        )

        if not self.should_require_approval(approval_type, risk_level):
            req.status = ApprovalStatus.APPROVED
            req.resolved_at = datetime.now(timezone.utc)
            req.reason = "Auto-approved by policy threshold settings."
            self.history.append(req)
            return True

        self.pending_requests[req.id] = req
        self.history.append(req)

        # If a sync or async callback is registered, trigger it immediately
        if self.approval_callback:
            try:
                import inspect

                if inspect.iscoroutinefunction(self.approval_callback):
                    approved = await self.approval_callback(req)
                else:
                    approved = self.approval_callback(req)

                if approved:
                    self.resolve_request(
                        req.id, ApprovalStatus.APPROVED, "Approved by callback."
                    )
                    return True
                else:
                    self.resolve_request(
                        req.id, ApprovalStatus.DENIED, "Denied by callback."
                    )
                    return False
            except Exception as e:
                self.resolve_request(
                    req.id, ApprovalStatus.DENIED, f"Callback execution failure: {e!s}"
                )
                return False

        # In interactive serving mode without callback, caller can poll and resolve request later.
        # But for direct synchronous orchestrator executions, if no callback exists and we require approval,
        # we default to denying unless the mode is non-interactive.
        if settings.security.approval_mode == "interactive":
            # Wait for external approval via API or CLI (interactive caller handles this)
            return False

        return False

    def resolve_request(
        self, request_id: str, status: ApprovalStatus, reason: str | None = None
    ) -> bool:
        """Resolves a pending approval request."""
        if request_id not in self.pending_requests:
            return False

        req = self.pending_requests[request_id]
        req.status = status
        req.resolved_at = datetime.now(timezone.utc)
        req.reason = reason

        # Remove from pending list
        del self.pending_requests[request_id]
        return True

    def get_pending(self, session_id: str | None = None) -> list[ApprovalRequest]:
        """Lists active pending approval requests."""
        if session_id:
            return [
                r for r in self.pending_requests.values() if r.session_id == session_id
            ]
        return list(self.pending_requests.values())
