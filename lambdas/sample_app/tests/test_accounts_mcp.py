"""The accounts MCP service: what each tool needs, what each role gets, and that /mcp
is reachable through the real handler."""

from __future__ import annotations

import asyncio
import json
import pathlib
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware

from sample_app.accounts_mcp import http as mcp_http
from sample_app.accounts_mcp.tools import PERMISSION
from sample_app.routers import ap, approvals, ar, dashboard
from sample_app.tests.conftest import ADMIN_PERMISSIONS, build_director

ROOT = pathlib.Path(__file__).resolve().parents[3]
ROLES: dict[str, list[str]] = json.loads((ROOT / "deploy" / "sample-app" / "roles.json").read_text())["roles"]
DECLARED = {p["key"] for p in json.loads((ROOT / "deploy" / "sample-app" / "permissions.json").read_text())["permissions"]}

#: The web route each tool does its work through.
ROUTE_OF = {
    "accounts_summary": dashboard.get_dashboard,
    "list_invoices": ar.list_invoices,
    "overdue_receivables": ar.list_invoices,
    "raise_invoice": ar.create_invoice,
    "send_invoice_for_approval": ar.submit_invoice,
    "list_bills": ap.list_bills,
    "record_bill": ap.create_bill,
    "send_bill_for_approval": ap.submit_bill,
    "approval_queue": approvals.list_approvals,
    "decide": approvals.approve,
}

ARGS: dict[str, dict[str, Any]] = {
    "who_am_i": {},
    "accounts_summary": {},
    "list_invoices": {},
    "overdue_receivables": {"as_of": "2026-11-07"},
    "raise_invoice": {"customer_name": "Acme Ltd", "amount": 250.0, "due_date": "2026-12-01"},
    "send_invoice_for_approval": {"invoice_id": "inv-1"},
    "list_bills": {"status": "pending"},
    "record_bill": {"vendor_name": "Globex", "amount": 99.5},
    "send_bill_for_approval": {"bill_id": "bill-1"},
    "approval_queue": {},
    "decide": {"record_type": "invoice", "record_id": "inv-1", "decision": "reject"},
}


def _route_permissions() -> dict[Any, str]:
    found: dict[Any, str] = {}
    for router in (dashboard.router, ar.router, ap.router, approvals.router):
        for route in router.routes:
            for dep in getattr(route, "dependencies", []):
                for cell in getattr(dep.dependency, "__closure__", None) or ():
                    if isinstance(cell.cell_contents, str):
                        found[route.endpoint] = cell.cell_contents
    return found


def test_the_permission_table_is_the_servers_tools():
    listed = asyncio.run(mcp_http.SERVER.list_tools())
    assert {t.name for t in listed} == set(PERMISSION) == set(ARGS)


def test_each_tool_needs_what_its_web_route_enforces():
    web = _route_permissions()
    for tool, route in ROUTE_OF.items():
        assert PERMISSION[tool] == web[route], tool


def test_every_tool_permission_is_deployed():
    assert {p for p in PERMISSION.values() if p} <= DECLARED


# ── Through the transport ────────────────────────────────────────────────────


def _books() -> MagicMock:
    repo = MagicMock()
    repo.list_invoices.return_value = [
        {"invoice_id": "inv-1", "customer_name": "Acme", "amount": "100", "status": "draft", "due_date": "2026-10-01"},
        {"invoice_id": "inv-2", "customer_name": "Initech", "amount": "40", "status": "paid", "due_date": "2026-09-01"},
        {"invoice_id": "inv-3", "customer_name": "Hooli", "amount": "60.5", "status": "pending_approval", "due_date": "2026-08-15"},
        {"invoice_id": "inv-4", "customer_name": "Umbrella", "amount": "10", "status": "draft", "due_date": "2026-12-31"},
    ]
    repo.list_bills.return_value = [{"bill_id": "bill-1", "status": "pending"}, {"bill_id": "bill-2", "status": "approved"}]
    repo.list_pending_approvals.return_value = []
    repo.dashboard_summary.return_value = {"outstanding_invoices": 3}
    repo.create_invoice.side_effect = lambda data: {"invoice_id": "inv-9", "status": "draft", **data}
    repo.create_bill.side_effect = lambda data: {"bill_id": "bill-9", "status": "pending", **data}
    repo.submit_for_approval.side_effect = lambda t, i, by: {"id": i, "status": "pending_approval", "submitted_by": by}
    repo.reject.side_effect = lambda t, i: {"id": i, "status": "rejected"}
    return repo


def _director(permissions):
    director = build_director(set(permissions))
    director._repository = _books()
    return director


def _app(permissions=None, director=None) -> FastAPI:
    director = director or _director(permissions)
    app = FastAPI()

    class Attach(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.director = director
            return await call_next(request)

    app.add_middleware(Attach)
    app.include_router(mcp_http.router)
    return app


def _rpc(app: FastAPI, method: str, params: dict | None = None) -> dict:
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://acme.api.test") as c:
            r = await c.post("/mcp", json={"jsonrpc": "2.0", "id": 7, "method": method, "params": params or {}},
                             headers={"accept": "application/json, text/event-stream"})
            assert r.status_code == 200, r.text
            return r.json()["result"]
    return asyncio.run(go())


def _tool(app: FastAPI, name: str) -> tuple[bool, Any]:
    result = _rpc(app, "tools/call", {"name": name, "arguments": ARGS[name]})
    text = result["content"][0]["text"] if result["content"] else "null"
    if result.get("isError"):
        return False, text
    structured = result.get("structuredContent")
    if structured is not None:
        return True, structured.get("result", structured)
    return True, json.loads(text)


def test_initialize_answers_as_ems_accounts():
    result = _rpc(_app(ADMIN_PERMISSIONS), "initialize", {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "pytest", "version": "1"}})
    assert result["serverInfo"]["name"] == "ems-accounts"
    assert "approval queue" in result["instructions"]


@pytest.mark.parametrize("role", sorted(ROLES))
def test_each_role_gets_exactly_its_tools(role, monkeypatch):
    monkeypatch.setattr(approvals, "fingerprint_async", lambda *a, **k: None)
    app = _app(ROLES[role])
    for tool, needed in PERMISSION.items():
        ok, answer = _tool(app, tool)
        allowed = needed is None or needed in ROLES[role]
        assert ok is allowed, f"{role} / {tool}: {answer}"
        if not allowed:
            assert f"needs the '{needed}' permission" in answer


def test_overdue_receivables_is_unpaid_and_past_due_oldest_first():
    ok, report = _tool(_app(ROLES["viewer"]), "overdue_receivables")
    assert ok
    assert [i["invoice_id"] for i in report["invoices"]] == ["inv-3", "inv-1"]
    assert (report["count"], report["total"], report["as_of"]) == (2, 160.5, "2026-11-07")


def test_list_bills_filters_by_status():
    ok, bills = _tool(_app(ROLES["viewer"]), "list_bills")
    assert ok and [b["bill_id"] for b in bills] == ["bill-1"]


def test_who_am_i_is_the_caller():
    ok, me = _tool(_app({"ap.bills.read"}), "who_am_i")
    assert ok and (me["tenant"], me["permissions"]) == ("t-test", ["ap.bills.read"])


def test_a_refusal_from_the_books_is_a_tool_error():
    from sample_app.repository import TransitionNotAllowedError

    director = _director(ADMIN_PERMISSIONS)
    director._repository.submit_for_approval.side_effect = TransitionNotAllowedError("invoice inv-1 is approved")
    ok, text = _tool(_app(director=director), "send_invoice_for_approval")
    assert not ok and "Not possible in its current state" in text and "inv-1 is approved" in text


# ── Through the real handler, as the bearer API delivers it ─────────────────


def test_an_api_gateway_event_for_mcp_reaches_the_service():
    from sample_app import handler

    event = {
        "version": "2.0", "routeKey": "ANY /", "rawPath": "/mcp", "rawQueryString": "",
        "headers": {"host": "acme.api.porth-dau.ems.estynsoftware.cloud", "content-type": "application/json",
                    "accept": "application/json, text/event-stream", "authorization": "Bearer x"},
        "requestContext": {
            "http": {"method": "POST", "path": "/mcp", "protocol": "HTTP/1.1", "sourceIp": "203.0.113.9", "userAgent": "t"},
            "domainName": "acme.api.porth-dau.ems.estynsoftware.cloud", "stage": "$default", "requestId": "r",
            "authorizer": {"lambda": {"tenant_id": "acme", "environment": "porth-dau", "user_id": "auth0|7",
                                      "roles": "r-1", "permissions": ",".join(ROLES["viewer"]), "auth_source": "jwt"}},
        },
        "body": json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                            "params": {"name": "who_am_i", "arguments": {}}}),
        "isBase64Encoded": False,
    }
    asyncio.set_event_loop(asyncio.new_event_loop())  # Mangum 0.17 uses get_event_loop()
    out = handler.handler(event, None)
    assert out["statusCode"] == 200, out
    result = json.loads(out["body"])["result"]
    me = result.get("structuredContent") or json.loads(result["content"][0]["text"])
    assert (me["tenant"], me["environment"], me["user"]) == ("acme", "porth-dau", "auth0|7")
