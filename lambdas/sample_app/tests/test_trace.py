"""The sample app's request trace: every request is followable, nothing secret is written."""

from __future__ import annotations

import asyncio
import json
import logging

TOKEN = "prth_never_in_a_log_line"


def test_a_request_is_followable_and_leaks_nothing(caplog):
    from sample_app import handler

    caplog.set_level(logging.DEBUG, logger="sample_app")
    event = {
        "version": "2.0", "routeKey": "$default", "rawPath": "/", "rawQueryString": "",
        "stageVariables": {"mapping_key": "mcp"},
        "cookies": ["__Secure-porth_session=cookie-never-logged"],
        "headers": {"host": "acme.api.porth-dau.ems.estynsoftware.cloud", "content-type": "application/json",
                    "accept": "application/json, text/event-stream", "authorization": f"Bearer {TOKEN}"},
        "requestContext": {
            "http": {"method": "POST", "path": "/", "protocol": "HTTP/1.1", "sourceIp": "203.0.113.9", "userAgent": "t"},
            "domainName": "acme.api.porth-dau.ems.estynsoftware.cloud", "stage": "$default", "requestId": "Gg-rid=",
            "authorizer": {"lambda": {"tenant_id": "acme", "environment": "porth-dau", "user_id": "auth0|7",
                                      "roles": "r", "permissions": "dashboard.read", "auth_source": "jwt",
                                      "SecretAccessKey": "secret-never-logged"}},
        },
        "body": json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                            "params": {"name": "who_am_i", "arguments": {}}}),
        "isBase64Encoded": False,
    }
    asyncio.set_event_loop(asyncio.new_event_loop())
    out = handler.handler(event, None)
    assert out["statusCode"] == 200, out

    lines = [r.getMessage() for r in caplog.records]
    text = "\n".join(lines)
    request_in = next(l for l in lines if l.startswith("request.in "))
    assert "rid=Gg-rid=" in request_in and "raw_path=/" in request_in and "path=/mcp" in request_in
    assert f"authorization=bearer-prth(len={len(TOKEN)})" in request_in
    assert "tenant_id=acme" in request_in and "auth_source=jwt" in request_in
    assert "SecretAccessKey" in request_in  # the key's NAME, so a missing credential shows
    assert any(l.startswith("request.out ") and "status=200" in l for l in lines)
    for secret in (TOKEN, "cookie-never-logged", "secret-never-logged"):
        assert secret not in text, f"{secret[:10]}… reached the log"
