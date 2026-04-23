from fastapi import APIRouter, Request, Depends
from ..dependencies import require_permission
from ..repository import SampleAppRepository

router = APIRouter(prefix="/sample", tags=["dashboard"])

@router.get("/dashboard", dependencies=[Depends(require_permission("dashboard.read"))])
def get_dashboard(request: Request) -> dict:
    repo = SampleAppRepository(request.state.porth.dynamodb)
    return repo.dashboard_summary(request.state.porth.tenant_id)
