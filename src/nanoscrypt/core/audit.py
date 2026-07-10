from datetime import UTC, datetime
from enum import Enum
from typing import Any

import structlog

from nanoscrypt.models.database import DBAuditLog

logger = structlog.get_logger()


class AuditEventType(str, Enum):
    LLM_CALL = "llm_call"
    TOOL_GENERATED = "tool_generated"
    TOOL_EXECUTED = "tool_executed"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    POLICY_VIOLATION = "policy_violation"
    REPAIR_ATTEMPTED = "repair_attempted"
    ERROR = "error"


class AuditLogger:
    """Immutable audit trail for writing governance and runtime metrics to database."""

    def __init__(self, session_factory: Any):
        self.session_factory = session_factory

    async def log_event(
        self,
        event_type: AuditEventType,
        session_id: str,
        agent_name: str,
        details: dict[str, Any],
        cost: float = 0.0,
        token_usage: int = 0,
    ) -> None:
        """Persists an audit log event."""
        log = logger.bind(
            component="audit_logger",
            event_type=event_type,
            session_id=session_id,
            agent=agent_name,
        )
        log.debug("audit_logging_event")

        async with self.session_factory() as session:
            async with session.begin():
                record = DBAuditLog(
                    event_type=event_type.value,
                    session_id=session_id,
                    agent_name=agent_name,
                    details=details,
                    cost=cost,
                    token_usage=token_usage,
                    timestamp=datetime.now(UTC),
                )
                session.add(record)
            await session.commit()
        log.info("audit_event_logged", cost=cost, token_usage=token_usage)
