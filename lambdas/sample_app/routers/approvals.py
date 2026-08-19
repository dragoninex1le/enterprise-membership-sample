from fastapi import APIRouter, Depends
from ..dependencies import porth, require_permission
from ..director import SampleAppDirector

router = APIRouter(prefix="/sample/approvals", tags=["approvals"])

@router.get("", dependencies=[Depends(require_permission("approvals.read"))])
def list_approvals(director: SampleAppDirector = Depends(porth)) -> list[dict]:
    return director.repository.list_pending_approvals(director.tenant_id)

@router.post("/{record_id}/approve", dependencies=[Depends(require_permission("approvals.write"))])
def approve(record_id: str, director: SampleAppDirector = Depends(porth)) -> dict:
    return director.repository.approve(director.tenant_id, record_id)

@router.post("/{record_id}/reject", dependencies=[Depends(require_permission("approvals.write"))])
def reject(record_id: str, director: SampleAppDirector = Depends(porth)) -> dict:
    return director.repository.reject(director.tenant_id, record_id)
