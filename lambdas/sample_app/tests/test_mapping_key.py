"""Mapped APIs deliver key-stripped paths; the app restores the key before routing.

Found live on porth-dau: POST {tenant}.api.../suppliers/session reached the supplier
portal as /session (FastAPI 404), and a request for exactly .../mcp matched no route.
"""

from __future__ import annotations

import asyncio
import json
import pathlib

import pytest

from sample_app.mapping_key import restore_mapping_key
from sample_app.tests.test_bearer_surface import _template

ROOT = pathlib.Path(__file__).resolve().parents[3]
ROLES = json.loads((ROOT / "deploy" / "sample-app" / "roles.json").read_text())["roles"]


def event(path: str, key: str | None, **extra) -> dict:
    e = {"rawPath": path, "requestContext": {"http": {"path": path, "method": "GET"}}}
    if key is not None:
        e["stageVariables"] = {"mapping_key": key}
    e.update(extra)
    return e


@pytest.mark.parametrize("path,key,expected", [
    ("/", "mcp", "/mcp"),                       # the bare key, via $default
    ("", "mcp", "/mcp"),
    ("/session", "suppliers", "/suppliers/session"),
    ("/invoices/b-1", "suppliers", "/suppliers/invoices/b-1"),
    ("/mcp", "mcp", "/mcp"),                    # already keyed: left alone
    ("/suppliers/me", "suppliers", "/suppliers/me"),
    ("/sample/ar/invoices", None, "/sample/ar/invoices"),  # browser API: no key
])
def test_restore(path, key, expected):
    out = restore_mapping_key(event(path, key))
    assert out["rawPath"] == expected and out["requestContext"]["http"]["path"] == expected


def test_the_callers_event_is_not_mutated():
    original = event("/session", "suppliers")
    restore_mapping_key(original)
    assert original["rawPath"] == "/session"


def test_mcp_with_the_key_stripped_reaches_the_service_through_the_real_handler():
    from sample_app import handler

    stripped = {
        "version": "2.0", "routeKey": "$default", "rawPath": "/", "rawQueryString": "",
        "stageVariables": {"mapping_key": "mcp"},
        "headers": {"host": "acme.api.porth-dau.ems.estynsoftware.cloud", "content-type": "application/json",
                    "accept": "application/json, text/event-stream", "authorization": "Bearer x"},
        "requestContext": {
            "http": {"method": "POST", "path": "/", "protocol": "HTTP/1.1", "sourceIp": "203.0.113.9", "userAgent": "t"},
            "domainName": "acme.api.porth-dau.ems.estynsoftware.cloud", "stage": "$default", "requestId": "r",
            "authorizer": {"lambda": {"tenant_id": "acme", "environment": "porth-dau", "user_id": "auth0|7",
                                      "roles": "r", "permissions": ",".join(ROLES["viewer"]), "auth_source": "jwt"}},
        },
        "body": json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                            "params": {"name": "who_am_i", "arguments": {}}}),
        "isBase64Encoded": False,
    }
    asyncio.set_event_loop(asyncio.new_event_loop())
    out = handler.handler(stripped, None)
    assert out["statusCode"] == 200, out
    me = json.loads(out["body"])["result"]["structuredContent"]
    assert me["tenant"] == "acme"


@pytest.fixture(scope="module")
def resources():
    return _template()["Resources"]


@pytest.mark.parametrize("stage,key", [("SampleAppBearerStage", "mcp"), ("SampleAppSuppliersStage", "suppliers")])
def test_each_mapped_stage_declares_its_key(resources, stage, key):
    assert resources[stage]["Properties"]["StageVariables"] == {"mapping_key": key}
    api = resources[stage]["Properties"]["ApiId"]["Ref"]
    mapped_keys = {r["Properties"]["ApiMappingKey"] for r in resources.values()
                   if r["Type"] == "AWS::ApiGatewayV2::ApiMapping" and r["Properties"]["ApiId"] == {"Ref": api}}
    assert mapped_keys == {key}, "the stage variable must name the key the API is actually mapped under"


@pytest.mark.parametrize("api,authorizer", [("SampleAppBearerApi", "SampleAppBearerAuthorizer"),
                                            ("SampleAppSuppliersApi", "SampleAppSuppliersAuthorizer")])
def test_the_bare_key_has_an_authorized_catch_all(resources, api, authorizer):
    defaults = [r["Properties"] for r in resources.values() if r["Type"] == "AWS::ApiGatewayV2::Route"
                and r["Properties"]["ApiId"] == {"Ref": api} and r["Properties"]["RouteKey"] == "$default"]
    assert len(defaults) == 1
    assert (defaults[0]["AuthorizationType"], defaults[0]["AuthorizerId"]) == ("CUSTOM", {"Ref": authorizer})
