from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..dependencies import porth, require_permission
from ..director import SampleAppDirector
from ..repository import TransitionNotAllowedError

router = APIRouter(prefix="/sample/ap", tags=["accounts-payable"])

class CreateBillRequest(BaseModel):
    vendor_name: str
    amount: float
    due_date: str = ""

@router.get("/bills", dependencies=[Depends(require_permission("ap.bills.read"))])
def list_bills(director: SampleAppDirector = Depends(porth)) -> list[dict]:
    return director.repository.list_bills()

@router.post("/bills", dependencies=[Depends(require_permission("ap.bills.write"))])
def create_bill(body: CreateBillRequest, director: SampleAppDirector = Depends(porth)) -> dict:
    return director.repository.create_bill(
        {**body.model_dump(), "created_by": director.user_id},
    )


@router.post("/bills/{record_id}/submit", dependencies=[Depends(require_permission("ap.bills.write"))])
def submit_bill(record_id: str, director: SampleAppDirector = Depends(porth)) -> dict:
    """Put this bill in front of an approver.

    The step that was missing (PORTH-597). Guarded by `ap.bills.write` rather than by
    `approvals.write`, deliberately: submitting is something you do to your OWN
    record and deciding is something someone else does to it. One permission for
    both would let every author approve their own work.
    """
    try:
        return director.repository.submit_for_approval(
            "bill", record_id, by=director.user_id
        )
    except TransitionNotAllowedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
