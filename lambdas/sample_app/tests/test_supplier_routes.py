"""The supplier portal in the sample app: suppliers reach /suppliers/* and nothing else,
and see only their own invoices.

API Gateway events through the real handler, so the boundary is exercised where it
runs: after the Director is built from Porth's context, before any router.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import re
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.routing import APIRoute

from sample_app import handler
from sample_app.director import SampleAppDirector

ROOT = pathlib.Path(__file__).resolve().parents[3]
ROLES = json.loads((ROOT / "deploy" / "sample-app" / "roles.json").read_text())["roles"]
HOST = "acme.api.porth-dau.ems.estynsoftware.cloud"


def porth_context(permissions=ROLES["supplier"], **changes) -> dict[str, str]:
    """What Porth's bearer authorizer hands the app for a supplier contact's session.
    No user_id: Porth creates no user for a delegated principal."""
    ctx = {"tenant_id": "acme", "environment": "porth-dau", "organization_id": "org-acme",
           "external_id": "supplierlink:sup-globex.c-41", "roles": "r-supplier",
           "permissions": ",".join(sorted(permissions)), "auth_source": "exchange",
           "connector_type": "supplierlink", "store_external_id": "sup-globex", "delegated_session_id": "ses-1"}
    ctx.update(changes)
    return ctx


def send(method: str, path: str, ctx: dict, body: Any = None) -> tuple[int, Any]:
    event = {
        "version": "2.0", "routeKey": "ANY /{proxy+}", "rawPath": path, "rawQueryString": "",
        "headers": {"host": HOST, "content-type": "application/json", "authorization": "Bearer prth_x"},
        "requestContext": {"http": {"method": method, "path": path, "protocol": "HTTP/1.1",
                                    "sourceIp": "203.0.113.4", "userAgent": "t"},
                           "domainName": HOST, "stage": "$default", "requestId": "r",
                           "authorizer": {"lambda": ctx}},
        "body": json.dumps(body) if body is not None else "", "isBase64Encoded": False,
    }
    out = handler.handler(event, None)
    try:
        return out["statusCode"], json.loads(out["body"] or "null")
    except json.JSONDecodeError:
        return out["statusCode"], out["body"]


@pytest.fixture(autouse=True)
def books(monkeypatch):
    bills = {
        "b-mine": {"bill_id": "b-mine", "supplier_id": "sup-globex", "status": "pending_approval"},
        "b-theirs": {"bill_id": "b-theirs", "supplier_id": "sup-initech", "status": "approved"},
        "b-internal": {"bill_id": "b-internal", "status": "pending"},
    }
    repo = MagicMock()
    repo.supplier_invoices.side_effect = lambda s: [b for b in bills.values() if b.get("supplier_id") == s]
    repo.supplier_invoice.side_effect = lambda s, i: bills[i] if i in bills and bills[i].get("supplier_id") == s else None
    repo.create_supplier_invoice.side_effect = lambda **kw: {"bill_id": "b-new", "status": "pending", **kw}
    monkeypatch.setattr(SampleAppDirector, "repository", property(lambda self: repo))
    asyncio.set_event_loop(asyncio.new_event_loop())
    return repo


def every_route():
    for route in handler.app.routes:
        if isinstance(route, APIRoute):
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                yield method, re.sub(r"\{[^}]+\}", "x1", route.path)


# ── The boundary ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("method,path", [r for r in every_route() if not r[1].startswith("/suppliers/")])
def test_a_supplier_reaches_nothing_but_the_portal(method, path):
    # Even holding every permission the buyer's own staff hold.
    everything = {p for grants in ROLES.values() for p in grants}
    assert send(method, path, porth_context(everything)) == (403, {"detail": "delegated_principal_refused"}), path


def test_the_sweep_covers_mcp_approvals_and_the_ledgers():
    paths = {p for _, p in every_route()}
    assert {"/mcp", "/sample/approvals", "/sample/ap/bills", "/sample/ar/invoices"} <= paths


@pytest.mark.parametrize("changes", [
    {"auth_source": "jwt", "connector_type": "", "store_external_id": ""},      # a signed-in person or MCP client
    {"auth_source": "session", "connector_type": "", "store_external_id": ""},  # a browser session
    {"connector_type": "another-network"},                                      # another connector's principal
    {"store_external_id": ""},                                                  # no supplier named
])
def test_the_portal_serves_supplier_contacts_only(changes):
    assert send("GET", "/suppliers/me", porth_context(**changes)) == (403, {"detail": "suppliers_only"})


# ── A supplier's own invoices ────────────────────────────────────────────────


def test_me_names_the_buyer_the_supplier_and_the_contact():
    status, me = send("GET", "/suppliers/me", porth_context())
    assert status == 200
    assert (me["buyer_tenant"], me["supplier"], me["contact"]) == ("acme", "sup-globex", "supplierlink:sup-globex.c-41")


def test_a_supplier_sees_only_their_own_invoices():
    status, listed = send("GET", "/suppliers/invoices", porth_context())
    assert status == 200 and [b["bill_id"] for b in listed] == ["b-mine"]
    assert send("GET", "/suppliers/invoices/b-mine", porth_context())[0] == 200
    assert send("GET", "/suppliers/invoices/b-theirs", porth_context())[0] == 404
    assert send("GET", "/suppliers/invoices/b-internal", porth_context())[0] == 404


def test_an_invoice_is_filed_under_porths_supplier_not_the_requests(books):
    status, made = send("POST", "/suppliers/invoices", porth_context(),
                        {"vendor_name": "Globex Corp", "amount": 1200, "supplier_reference": "INV-77",
                         "supplier_id": "sup-initech"})
    assert status == 200
    kwargs = books.create_supplier_invoice.call_args.kwargs
    assert kwargs["supplier_id"] == "sup-globex"
    assert kwargs["submitted_by"] == "supplierlink:sup-globex.c-41"
    assert "supplier_id" not in kwargs["data"]


@pytest.mark.parametrize("permissions,path,method,want", [
    (["supplier.invoices.read"], "/suppliers/invoices", "POST", 403),
    (["supplier.invoices.submit"], "/suppliers/invoices", "GET", 403),
    (["supplier.invoices.submit"], "/suppliers/invoices", "POST", 200),
])
def test_each_portal_action_needs_its_own_permission(permissions, path, method, want):
    body = {"vendor_name": "Globex", "amount": 5} if method == "POST" else None
    assert send(method, path, porth_context(permissions), body)[0] == want


def test_an_invoice_needs_a_positive_amount():
    assert send("POST", "/suppliers/invoices", porth_context(), {"vendor_name": "Globex", "amount": 0})[0] == 422
