from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from nanoscrypt.api.dependencies import get_registry
from nanoscrypt.api.schemas import AuditLogResponse
from nanoscrypt.core.registry import ToolRegistry
from nanoscrypt.models.database import DBAuditLog

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=list[AuditLogResponse])
async def query_audit_logs(
    session_id: str | None = Query(None, description="Filter logs by session ID"),
    event_type: str | None = Query(None, description="Filter logs by event type"),
    limit: int = Query(50, description="Maximum number of log entries to retrieve"),
    registry: ToolRegistry = Depends(get_registry),
):
    """Retrieves immutable audit logs from database with optional filters."""
    async with registry.session_factory() as session:
        stmt = select(DBAuditLog)

        # Apply filters
        if session_id:
            stmt = stmt.where(DBAuditLog.session_id == session_id)
        if event_type:
            stmt = stmt.where(DBAuditLog.event_type == event_type)

        stmt = stmt.order_by(DBAuditLog.timestamp.desc()).limit(limit)
        res = await session.execute(stmt)
        logs = res.scalars().all()

        response = []
        for l in logs:
            response.append(
                AuditLogResponse(
                    id=l.id,
                    event_type=l.event_type,
                    session_id=l.session_id,
                    agent_name=l.agent_name,
                    details=l.details,
                    cost=l.cost,
                    token_usage=l.token_usage,
                    timestamp=l.timestamp,
                )
            )
        return response


@router.get("/summary", response_model=dict[str, Any])
async def get_audit_summary(registry: ToolRegistry = Depends(get_registry)):
    """Aggregates costs and token usage totals across all runs."""
    async with registry.session_factory() as session:
        stmt = select(DBAuditLog.cost, DBAuditLog.token_usage)
        res = await session.execute(stmt)
        records = res.all()

        total_cost = sum(r[0] for r in records)
        total_tokens = sum(r[1] for r in records)

        return {
            "total_runs": len(records),
            "total_estimated_cost_usd": float(total_cost),
            "total_tokens_consumed": int(total_tokens),
        }
