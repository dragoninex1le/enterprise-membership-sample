import pytest
from starlette.testclient import TestClient
from sample_app.context import PorthContext
from unittest.mock import MagicMock

ADMIN_PERMISSIONS = {
    "dashboard.read", "ar.invoices.read", "ar.invoices.write",
    "ap.bills.read", "ap.bills.write", "approvals.read", "approvals.write",
}

@pytest.fixture
def mock_dynamodb():
    return MagicMock()

@pytest.fixture
def admin_context(mock_dynamodb):
    return PorthContext(
        tenant_id="t-test", user_id="u-1", organization_id="org-1", external_id="ext-1",
        roles=["tenant-admin", "controller"], permissions=ADMIN_PERMISSIONS, _dynamodb=mock_dynamodb,
    )

def make_test_app(context: PorthContext):
    from fastapi import FastAPI
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from sample_app.routers import dashboard, ar, ap, approvals

    test_app = FastAPI()

    class InjectPorth(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            request.state.porth = context
            return await call_next(request)

    test_app.add_middleware(InjectPorth)
    test_app.include_router(dashboard.router)
    test_app.include_router(ar.router)
    test_app.include_router(ap.router)
    test_app.include_router(approvals.router)
    return test_app

@pytest.fixture
def client(admin_context):
    return TestClient(make_test_app(admin_context))
