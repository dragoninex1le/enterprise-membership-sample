from fastapi import APIRouter, Request, Depends
from ..dependencies import require_permission
from ..repository import SampleAppRepository

router = APIRouter(prefix="/sample/approvals", tags=["approvals"])

@router.get("", dependencies=[Depends(require_permission("approvals.read"))])
def list_approvals(request: Request) -> list[dict]:
    return SampleAppRepository(request.state.porth.dynamodb).list_pending_approvals(request.state.porth.tenant_id)

@router.post("/{record_id}/approve", dependencies=[Depends(require_permission("approvals.write"))])
def approve(record_id: str, request: Request) -> dict:
    return SampleAppRepository(request.state.porth.dynamodb).approve(request.state.porth.tenant_id, record_id)

@router.post("/{record_id}/reject", dependencies=[Depends(require_permission("approvals.write"))])
def reject(record_id: str, request: Request) -> dict:
    return SampleAppRepository(request.state.porth.dynamodb).reject(request.state.porth.tenant_id, record_id)
