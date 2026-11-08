"""The supplier portal's debug trace: every request is followable, nothing secret is written."""

import json
import logging

import pytest

from supplier_portal import trace, web

HOST = "acme.api.porth-dau.ems.estynsoftware.cloud"
SECRET_ASSERTION = "eyJzZWNyZXQiOnRydWV9.c2VjcmV0LXBheWxvYWQ.c2lnbmF0dXJlLXNob3VsZC1uZXZlci1hcHBlYXI"
SECRET_TOKEN = "prth_should_never_appear_in_a_log_line"


def _event(path, method="POST", body=None, headers=None, mapping_key="suppliers", authorizer=None):
    return {
        "version": "2.0",
        "routeKey": f"{method} {path}",
        "rawPath": path,
        "rawQueryString": "",
        "cookies": ["__Secure-porth_session=cookie-value-never-logged"],
        "headers": {"host": HOST, "content-type": "application/json", **(headers or {})},
        "requestContext": {
            "http": {"method": method, "path": path, "sourceIp": "203.0.113.9", "protocol": "HTTP/1.1"},
            "requestId": "Gg-test-rid=",
            "stage": "$default",
            **({"authorizer": {"lambda": authorizer}} if authorizer else {}),
        },
        "stageVariables": {"mapping_key": mapping_key} if mapping_key else {},
        "body": json.dumps(body) if body is not None else None,
        "isBase64Encoded": False,
    }


@pytest.fixture()
def entry(monkeypatch):
    monkeypatch.delenv("SUPPLIERLINK_PUBLIC_KEY_PARAMETER", raising=False)
    monkeypatch.setattr(web, "_KEY", None)
    from supplier_portal import lambda_entry

    lambda_entry._adapter.app.dependency_overrides[web.links] = lambda: None
    yield lambda_entry
    lambda_entry._adapter.app.dependency_overrides.clear()


def test_a_request_is_followable_and_leaks_nothing(entry, caplog):
    caplog.set_level(logging.DEBUG, logger="supplier_portal")
    response = entry.handler(_event("/session", body={"assertion": SECRET_ASSERTION},
                                    headers={"authorization": f"Bearer {SECRET_TOKEN}",
                                             "x-csrf-token": "csrf-value-never-logged"},
                                    authorizer={"tenant_id": "acme", "AccessKeyId": "ASIA-never-logged"}))
    assert response["statusCode"] == 503  # no key parameter in the test: network_key_unavailable

    lines = [r.getMessage() for r in caplog.records]
    text = "\n".join(lines)
    request_in = next(l for l in lines if l.startswith("request.in "))
    assert "rid=Gg-test-rid=" in request_in
    assert "raw_path=/session" in request_in and "path=/suppliers/session" in request_in
    assert "mapping_key=suppliers" in request_in
    assert f"authorization=bearer-prth(len={len(SECRET_TOKEN)})" in request_in
    assert "cookies=__Secure-porth_session" in request_in and "csrf_header=True" in request_in
    assert "authorizer_keys=AccessKeyId,tenant_id" in request_in and "tenant_id=acme" in request_in
    assert any(l.startswith("session.in ") and f"assertion_len={len(SECRET_ASSERTION)}" in l for l in lines)
    assert any(l.startswith("request.out ") and "status=503" in l for l in lines)

    for secret in (SECRET_ASSERTION, SECRET_TOKEN, "cookie-value-never-logged",
                   "csrf-value-never-logged", "ASIA-never-logged"):
        assert secret not in text, f"{secret[:12]}… reached the log"


def test_the_preflight_decision_is_traced(entry, caplog):
    caplog.set_level(logging.DEBUG, logger="supplier_portal")
    entry.handler(_event("/sample/suppliers/link", method="OPTIONS", mapping_key=None, headers={
        "origin": "https://acme.porth-dau.ems.estynsoftware.cloud",
        "access-control-request-method": "GET",
        "access-control-request-headers": "authorization,x-csrf-token"}))
    cors = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("cors "))
    assert "granted=True" in cors and "own_ui=https://acme.porth-dau.ems.estynsoftware.cloud" in cors
    assert "requested_headers=authorization,x-csrf-token" in cors


@pytest.mark.parametrize("value,shape", [
    (None, "none"), ("Bearer ", "bearer-empty"), ("Bearer prth_abc", "bearer-prth(len=8)"),
    ("Bearer a.b.c", "bearer-jwt(len=5)"), ("Basic x", "other"),
])
def test_authorization_is_logged_by_shape_only(value, shape):
    assert trace.authorization_shape(value) == shape
