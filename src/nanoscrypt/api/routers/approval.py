from fastapi import APIRouter, Depends, HTTPException, Query

from nanoscrypt.api.dependencies import get_orchestrator
from nanoscrypt.api.schemas import ApprovalRecordResponse, ApprovalResolution
from nanoscrypt.core.approval import ApprovalStatus
from nanoscrypt.core.orchestrator import Orchestrator

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("/pending", response_model=list[ApprovalRecordResponse])
async def list_pending_approvals(
    session_id: str | None = Query(
        None, description="Filter approvals by active session ID"
    ),
    orchestrator: Orchestrator = Depends(get_orchestrator),
):
    """Lists all active human-in-the-loop pending approval requests."""
    pending = orchestrator.approval_gate.get_pending(session_id)
    response = []
    for r in pending:
        response.append(
            ApprovalRecordResponse(
                id=r.id,
                session_id=r.session_id,
                approval_type=r.approval_type.value,
                description=r.description,
                risk_level=r.risk_level,
                resource_details=r.resource_details,
                agent_name=r.agent_name,
                status=r.status.value,
                timestamp=r.timestamp,
                resolved_at=r.resolved_at,
                reason=r.reason,
            )
        )
    return response


@router.post("/{request_id}/resolve", response_model=dict[str, str])
async def resolve_approval_request(
    request_id: str,
    payload: ApprovalResolution,
    orchestrator: Orchestrator = Depends(get_orchestrator),
):
    """Approves or denies a pending approval request."""
    if request_id not in orchestrator.approval_gate.pending_requests:
        raise HTTPException(
            status_code=404, detail="Pending approval request not found."
        )

    status = ApprovalStatus.APPROVED if payload.approved else ApprovalStatus.DENIED
    success = orchestrator.approval_gate.resolve_request(
        request_id=request_id,
        status=status,
        reason=payload.reason or "Resolved via API call.",
    )
    if not success:
        raise HTTPException(
            status_code=500, detail="Failed to resolve approval request."
        )

    return {
        "status": "success",
        "message": f"Request has been resolved to '{status.value}'.",
    }
