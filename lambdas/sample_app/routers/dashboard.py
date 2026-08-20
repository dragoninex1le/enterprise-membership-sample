from fastapi import APIRouter, Depends
from ..dependencies import porth, require_permission
from ..director import SampleAppDirector

router = APIRouter(prefix="/sample", tags=["dashboard"])

@router.get("/dashboard", dependencies=[Depends(require_permission("dashboard.read"))])
def get_dashboard(director: SampleAppDirector = Depends(porth)) -> dict:
    repo = director.repository
    return repo.dashboard_summary(director.tenant_id)
