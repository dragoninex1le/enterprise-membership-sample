from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel
from ..dependencies import require_permission
from ..repository import SampleAppRepository

router = APIRouter(prefix="/sample/ap", tags=["accounts-payable"])

class CreateBillRequest(BaseModel):
    vendor_name: str
    amount: float
    due_date: str = ""

@router.get("/bills", dependencies=[Depends(require_permission("ap.bills.read"))])
def list_bills(request: Request) -> list[dict]:
    return SampleAppRepository(request.state.porth.dynamodb).list_bills(request.state.porth.tenant_id)

@router.post("/bills", dependencies=[Depends(require_permission("ap.bills.write"))])
def create_bill(body: CreateBillRequest, request: Request) -> dict:
    return SampleAppRepository(request.state.porth.dynamodb).create_bill(
        request.state.porth.tenant_id,
        {**body.model_dump(), "created_by": request.state.porth.user_id},
    )
