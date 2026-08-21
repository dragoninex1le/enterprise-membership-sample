from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..dependencies import porth, require_permission
from ..director import SampleAppDirector
from ..repository import TransitionNotAllowedError

router = APIRouter(prefix="/sample/ar", tags=["accounts-receivable"])

class CreateInvoiceRequest(BaseModel):
    customer_name: str
    amount: float
    due_date: str = ""

@router.get("/invoices", dependencies=[Depends(require_permission("ar.invoices.read"))])
def list_invoices(director: SampleAppDirector = Depends(porth)) -> list[dict]:
    return director.repository.list_invoices()

@router.post("/invoices", dependencies=[Depends(require_permission("ar.invoices.write"))])
def create_invoice(body: CreateInvoiceRequest, director: SampleAppDirector = Depends(porth)) -> dict:
    return director.repository.create_invoice(
        {**body.model_dump(), "created_by": director.user_id},
    )


@router.post("/invoices/{record_id}/submit", dependencies=[Depends(require_permission("ar.invoices.write"))])
def submit_invoice(record_id: str, director: SampleAppDirector = Depends(porth)) -> dict:
    """Put this invoice in front of an approver.

    The step that was missing (PORTH-597). Guarded by `ar.invoices.write` rather than by
    `approvals.write`, deliberately: submitting is something you do to your OWN
    record and deciding is something someone else does to it. One permission for
    both would let every author approve their own work.
    """
    try:
        return director.repository.submit_for_approval(
            "invoice", record_id, by=director.user_id
        )
    except TransitionNotAllowedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
