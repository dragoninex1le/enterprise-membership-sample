"""The suppliers API hands the portal /session for /suppliers/session (found live on
porth-dau); the entry point restores the key before FastAPI routes."""

import asyncio
import json

from supplier_portal import web


def test_a_key_stripped_session_request_reaches_the_session_route(network_key, monkeypatch):
    monkeypatch.setattr(web, "_KEY", network_key.public_key())
    from supplier_portal import lambda_entry

    # The links table is not consulted for an assertion that fails verification,
    # but FastAPI resolves the dependency first.
    lambda_entry._adapter.app.dependency_overrides[web.links] = lambda: None

    event = {
        "version": "2.0", "routeKey": "POST /session", "rawPath": "/session", "rawQueryString": "",
        "stageVariables": {"mapping_key": "suppliers"},
        "headers": {"host": "acme.api.porth-dau.ems.estynsoftware.cloud", "content-type": "application/json"},
        "requestContext": {"http": {"method": "POST", "path": "/session", "protocol": "HTTP/1.1",
                                    "sourceIp": "203.0.113.9", "userAgent": "t"},
                           "domainName": "acme.api.porth-dau.ems.estynsoftware.cloud", "stage": "$default",
                           "requestId": "r"},
        "body": json.dumps({"assertion": "not.an.assertion"}), "isBase64Encoded": False,
    }
    asyncio.set_event_loop(asyncio.new_event_loop())
    out = lambda_entry.handler(event, None)
    # The session route answered (it refused the assertion) — not FastAPI's 404.
    assert (out["statusCode"], json.loads(out["body"])) == (401, {"error": "assertion_rejected"})
