from fastapi import APIRouter, Depends
from pydantic import BaseModel
from ..dependencies import porth, require_permission
from ..director import SampleAppDirector

router = APIRouter(prefix="/sample/ap", tags=["accounts-payable"])

class CreateBillRequest(BaseModel):
    vendor_name: str
    amount: float
    due_date: str = ""

@router.get("/bills", dependencies=[Depends(require_permission("ap.bills.read"))])
def list_bills(director: SampleAppDirector = Depends(porth)) -> list[dict]:
    return director.repository.list_bills(director.tenant_id)

@router.post("/bills", dependencies=[Depends(require_permission("ap.bills.write"))])
def create_bill(body: CreateBillRequest, director: SampleAppDirector = Depends(porth)) -> dict:
    return director.repository.create_bill(
        director.tenant_id,
        {**body.model_dump(), "created_by": director.user_id},
    )
