from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel
from ..dependencies import require_permission
from ..repository import SampleAppRepository

router = APIRouter(prefix="/sample/ar", tags=["accounts-receivable"])

class CreateInvoiceRequest(BaseModel):
    customer_name: str
    amount: float
    due_date: str = ""

@router.get("/invoices", dependencies=[Depends(require_permission("ar.invoices.read"))])
def list_invoices(request: Request) -> list[dict]:
    return SampleAppRepository(request.state.porth.dynamodb).list_invoices(request.state.porth.tenant_id)

@router.post("/invoices", dependencies=[Depends(require_permission("ar.invoices.write"))])
def create_invoice(body: CreateInvoiceRequest, request: Request) -> dict:
    return SampleAppRepository(request.state.porth.dynamodb).create_invoice(
        request.state.porth.tenant_id,
        {**body.model_dump(), "created_by": request.state.porth.user_id},
    )
