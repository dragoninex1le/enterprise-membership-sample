from fastapi import APIRouter, Depends
from pydantic import BaseModel
from ..dependencies import porth, require_permission
from ..director import SampleAppDirector

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
