"""Linking a SupplierLink buyer account to a tenant: the store, and who may do it."""

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
from starlette.middleware.base import BaseHTTPMiddleware

from supplier_portal import web
from supplier_portal.links import ClaimedByAnotherTenant, Links

HOST = "acme.api.porth-dau.ems.estynsoftware.cloud"
ACME_UI = "https://acme.porth-dau.ems.estynsoftware.cloud"


@pytest.fixture
def table():
    with mock_aws():
        yield boto3.resource("dynamodb").create_table(
            TableName="ems-supplier-links-test", BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"},
                                  {"AttributeName": "tenant_pk", "AttributeType": "S"}],
            GlobalSecondaryIndexes=[{"IndexName": "by_tenant", "Projection": {"ProjectionType": "ALL"},
                                     "KeySchema": [{"AttributeName": "tenant_pk", "KeyType": "HASH"}]}],
        )


def admin(**context):
    from porth_common.director import Director

    ctx = {"tenant_id": "acme", "environment": "porth-dau", "user_id": "auth0|5", "porth_user_id": "pu-5",
           "roles": "r-admin", "permissions": "suppliers.manage", "auth_source": "session"}
    ctx.update(context)
    return Director({"requestContext": {"authorizer": {"lambda": ctx}}})


def client(table, who):
    api = web.build()
    api.dependency_overrides[web.links] = lambda: Links(table)

    class As(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.director = who
            return await call_next(request)

    api.add_middleware(As)
    return TestClient(api, base_url=f"https://{HOST}")


def test_linking_records_the_tenant_from_the_admins_own_session(table):
    r = client(table, admin()).put("/sample/suppliers/link", json={"buyer": "buyer-acme"}, headers={"origin": ACME_UI})
    assert r.status_code == 200, r.text
    assert r.json()["buyer"] == "buyer-acme" and "porth_context" not in r.json()
    assert r.headers["access-control-allow-origin"] == ACME_UI

    from porth_common.context.persisted import PersistedContext

    stored = Links(table).find("buyer-acme")
    record = PersistedContext.restore(stored.porth_context)
    assert (record.tenant_id, record.environment, stored.tenant) == ("acme", "porth-dau", "acme")
    assert client(table, admin()).get("/sample/suppliers/link").json()[0]["buyer"] == "buyer-acme"


def test_a_buyer_account_belongs_to_one_tenant(table):
    client(table, admin()).put("/sample/suppliers/link", json={"buyer": "buyer-acme"})
    r = client(table, admin(tenant_id="globex")).put("/sample/suppliers/link", json={"buyer": "buyer-acme"})
    assert r.status_code == 409
    with pytest.raises(ClaimedByAnotherTenant):
        Links(table).link(buyer="buyer-acme", tenant="globex", porth_context="{}", by="x")


def test_only_the_linking_tenant_can_unlink(table):
    client(table, admin()).put("/sample/suppliers/link", json={"buyer": "buyer-acme"})
    assert client(table, admin(tenant_id="globex")).delete("/sample/suppliers/link/buyer-acme").status_code == 404
    assert client(table, admin()).delete("/sample/suppliers/link/buyer-acme").status_code == 200
    assert Links(table).find("buyer-acme") is None


@pytest.mark.parametrize("context,status", [
    (dict(permissions="ap.bills.read"), 403),
    (dict(auth_source="exchange"), 403),
    (dict(tenant_id="platform", roles="platform-admin"), 403),
    (dict(tenant_id=""), 401),
])
def test_who_cannot_link(table, context, status):
    r = client(table, admin(**context)).put("/sample/suppliers/link", json={"buyer": "buyer-acme"})
    assert r.status_code == status, r.text
    assert Links(table).find("buyer-acme") is None


def test_cors_answers_only_this_hosts_own_ui(table):
    c = client(table, admin())
    assert "access-control-allow-origin" not in c.get(
        "/sample/suppliers/link", headers={"origin": "https://globex.porth-dau.ems.estynsoftware.cloud"}).headers
    ok = c.options("/sample/suppliers/link", headers={"origin": ACME_UI, "access-control-request-method": "PUT"})
    assert ok.status_code == 204 and ok.headers["access-control-allow-origin"] == ACME_UI
    assert c.options("/sample/suppliers/link", headers={"origin": "https://elsewhere.example"}).status_code == 403


def test_the_preflight_allows_every_header_the_spa_sends(table):
    """applyCookieAuth (frontend/src/api/client.ts) sends an empty bearer on every call,
    plus the CSRF and environment headers. If the preflight leaves one out, the browser
    refuses it and the Supplier network page shows only "Network Error"."""
    ok = client(table, admin()).options("/sample/suppliers/link", headers={
        "origin": ACME_UI, "access-control-request-method": "GET",
        "access-control-request-headers": "authorization,content-type,x-csrf-token,x-porth-environment"})
    allowed = {h.strip().lower() for h in ok.headers["access-control-allow-headers"].split(",")}
    assert ok.status_code == 204
    assert {"authorization", "content-type", "x-csrf-token", "x-porth-environment"} <= allowed
