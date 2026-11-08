"""GET /mcp/whoami: what Porth's bearer authorizer decided, and never its credentials.

Events shaped the way the bearer API delivers them: the path without its mapping
key, the key in the stage variables (mapping_key.py puts it back).
"""

from __future__ import annotations

import asyncio
import json

import pytest

from sample_app import handler

HOST = "acme.api.porth-dau.ems.estynsoftware.cloud"
OWN_UI = "https://acme.porth-dau.ems.estynsoftware.cloud"

SESSION_BOUND = {
    "tenant_id": "acme", "environment": "porth-dau", "auth_source": "bearer", "session_bound": "true",
    "route_kind": "session", "porth_user_id": "u-1", "external_id": "auth0|abc", "user_email": "a@acme.test",
    "roles": "r-admin", "permissions": "dashboard.read",
    # What must never leave: the request's narrowed credentials.
    "aws_access_key_id": "ASIA-NEVER-SHOWN", "aws_secret_access_key": "secret-never-shown",
    "aws_session_token": "session-token-never-shown", "aws_credentials_expiry": "2026-11-08T19:00:00+00:00",
}


def send(method: str, path: str, ctx: dict | None, headers: dict | None = None) -> dict:
    event = {
        "version": "2.0", "routeKey": f"{method} /{{proxy+}}", "rawPath": path, "rawQueryString": "",
        "headers": {"host": HOST, **(headers or {})},
        "requestContext": {"http": {"method": method, "path": path, "protocol": "HTTP/1.1",
                                    "sourceIp": "203.0.113.4", "userAgent": "t"},
                           "domainName": HOST, "stage": "$default", "requestId": "r",
                           **({"authorizer": {"lambda": ctx}} if ctx is not None else {})},
        "stageVariables": {"mapping_key": "mcp"},
        "body": "", "isBase64Encoded": False,
    }
    return handler.handler(event, None)


@pytest.fixture(autouse=True)
def loop():
    asyncio.set_event_loop(asyncio.new_event_loop())


def test_it_reports_a_session_bound_bearer():
    out = send("GET", "/whoami", SESSION_BOUND, {"authorization": "Bearer eyJ.a.b"})
    assert out["statusCode"] == 200
    body = json.loads(out["body"])
    assert body["auth_source"] == "bearer" and body["session_bound"] == "true"
    assert body["tenant_id"] == "acme" and body["environment"] == "porth-dau"


def test_it_never_returns_the_credentials():
    out = send("GET", "/whoami", SESSION_BOUND, {"authorization": "Bearer eyJ.a.b"})
    assert not {k for k in json.loads(out["body"]) if k.startswith("aws_")}
    for secret in ("ASIA-NEVER-SHOWN", "secret-never-shown", "session-token-never-shown"):
        assert secret not in out["body"]


def test_without_porths_context_it_is_a_401():
    assert send("GET", "/whoami", None)["statusCode"] == 401


def test_a_preflight_reaches_the_app_and_allows_authorization():
    """Which origins it grants is cors.py's (test_tenant_api_host_cors.py); here, that
    the open OPTIONS route's preflight is answered by the app with Authorization allowed."""
    out = send("OPTIONS", "/whoami", None, {"origin": OWN_UI, "access-control-request-method": "GET",
                                            "access-control-request-headers": "authorization"})
    assert out["statusCode"] == 200
    headers = {k.lower(): v for k, v in out["headers"].items()}
    assert "access-control-allow-origin" in headers
    assert "authorization" in headers["access-control-allow-headers"].lower()
