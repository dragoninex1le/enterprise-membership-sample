"""Test fixtures — now injecting a Director rather than a hand-rolled context.

PORTH-613. The old fixture built a `PorthContext` and a middleware that stapled
it to `request.state.porth`. That mirrored production only for as long as
production kept its own parser, which is exactly the duplication this ticket
removed.

The Director is built the way the middleware builds it — from an authorizer
event — so what the tests exercise is what the authorizer actually sends. Its
data connection is the one thing stubbed, because a test has no credentials to
narrow.
"""
import pytest
from unittest.mock import MagicMock
from starlette.testclient import TestClient

from sample_app.director import SampleAppDirector

ADMIN_PERMISSIONS = {
    "dashboard.read", "ar.invoices.read", "ar.invoices.write",
    "ap.bills.read", "ap.bills.write", "approvals.read", "approvals.write",
}


@pytest.fixture
def mock_dynamodb():
    return MagicMock()


def build_director(permissions=None, *, dynamodb=None) -> SampleAppDirector:
    """A Director as the authorizer would produce it, with a stubbed connection."""
    event = {
        "requestContext": {
            "authorizer": {
                "lambda": {
                    "tenant_id": "t-test",
                    "user_id": "u-1",
                    "organization_id": "org-1",
                    "external_id": "ext-1",
                    "roles": "tenant-admin,controller",
                    "permissions": ",".join(sorted(
                        ADMIN_PERMISSIONS if permissions is None else permissions
                    )),
                }
            }
        }
    }
    director = SampleAppDirector(event)
    if dynamodb is not None:
        from sample_app.repository import SampleAppRepository

        director._repository = SampleAppRepository(dynamodb)
    return director


@pytest.fixture
def admin_context(mock_dynamodb):
    return build_director(dynamodb=mock_dynamodb)


def make_test_app(director: SampleAppDirector):
    from fastapi import FastAPI
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request

    from sample_app.routers import dashboard, ar, ap, approvals

    test_app = FastAPI()

    class InjectDirector(BaseHTTPMiddleware):
        """Stands in for DirectorMiddleware, which needs a real Lambda event."""

        async def dispatch(self, request: Request, call_next):
            request.state.director = director
            return await call_next(request)

    test_app.add_middleware(InjectDirector)
    for router in (dashboard.router, ar.router, ap.router, approvals.router):
        test_app.include_router(router)
    return test_app


@pytest.fixture
def client(admin_context):
    return TestClient(make_test_app(admin_context))
