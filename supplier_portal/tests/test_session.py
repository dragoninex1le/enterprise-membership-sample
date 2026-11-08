"""POST /suppliers/session against a stand-in for Porth's delegated mint."""

import logging
import time

import pytest
from fastapi.testclient import TestClient

from supplier_portal import web
from supplier_portal.assertion import issue
from supplier_portal.links import BuyerLink

HOST = "acme.api.porth-dau.ems.estynsoftware.cloud"
CONTEXT = '{"environment":"porth-dau","tenant_id":"acme","trace_id":"tr-1"}'
SECRET_TOKEN = "prth_must_never_be_logged"


class OneLink:
    def __init__(self, link=None):
        self.link = link

    def find(self, buyer):
        return self.link if self.link and self.link.buyer == buyer else None


def linked(tenant="acme", context=CONTEXT):
    return BuyerLink(buyer="buyer-acme", tenant=tenant, porth_context=context, linked_by="pu-9", linked_at="t")


class FakePorth:
    """Answers like Porth's mint; records what it was asked."""

    def __init__(self, answer=None):
        self.asked = []
        self.answer = answer

    def __call__(self, record, body):
        self.asked.append((record, body))
        if self.answer is not None:
            return self.answer
        return {"ok": True, "token": SECRET_TOKEN, "session_id": "ses-1",
                "expires_at": body["host_credential_expires_at"], "api_base_url": f"https://{HOST}"}


@pytest.fixture
def make(network_key, monkeypatch):
    monkeypatch.setattr(web, "_KEY", network_key.public_key())

    def client(link=None, porth=None):
        api = web.build()
        api.dependency_overrides[web.links] = lambda: OneLink(link)
        api.dependency_overrides[web.mint_transport] = lambda: porth
        return TestClient(api, base_url=f"https://{HOST}")

    return client


def assertion_for(key, **changes):
    now = int(time.time())
    claims = dict(iss="supplierlink", aud="ems-accounts", sub="c-41", jti=f"a-{time.monotonic_ns()}",
                  iat=now, exp=now + 120, buyer="buyer-acme", supplier="sup-globex", role="billing")
    claims.update(changes)
    return issue(claims, private_key=key)


def post(client, token, host=HOST):
    return client.post("/suppliers/session", json={"assertion": token}, headers={"host": host})


def test_a_supplier_contact_gets_a_session_in_the_linked_tenant(make, network_key):
    porth = FakePorth()
    answer = post(make(linked(), porth), assertion_for(network_key))
    assert answer.status_code == 200, answer.text
    assert answer.json()["session_id"] == "ses-1" and answer.json()["token"] == SECRET_TOKEN
    record, body = porth.asked[0]
    assert (record.tenant_id, record.environment) == ("acme", "porth-dau")
    assert body == {
        "connector_type": "supplierlink",
        "external_id": "sup-globex.c-41",
        "verification": {"reference": body["verification"]["reference"],
                         "method": "supplierlink-es256-assertion", "verified_at": body["verification"]["verified_at"]},
        "host_credential_expires_at": body["host_credential_expires_at"],
        "store_external_id": "sup-globex",
        "role_claim": "billing",
    }
    assert body["verification"]["reference"].startswith("buyer-acme/")


def test_an_unverifiable_assertion_is_one_answer(make, network_key):
    from cryptography.hazmat.primitives.asymmetric import ec

    porth = FakePorth()
    client = make(linked(), porth)
    for bad in ("nonsense", assertion_for(ec.generate_private_key(ec.SECP256R1())), assertion_for(network_key, aud="x")):
        r = post(client, bad)
        assert (r.status_code, r.json()) == (401, {"error": "assertion_rejected"})
    assert not porth.asked


def test_a_buyer_that_is_not_linked(make, network_key):
    porth = FakePorth()
    r = post(make(None, porth), assertion_for(network_key))
    assert (r.status_code, r.json()) == (403, {"error": "buyer_not_linked"}) and not porth.asked


def test_presented_on_another_tenants_host(make, network_key):
    porth = FakePorth()
    r = post(make(linked(), porth), assertion_for(network_key), host="globex.api.porth-dau.ems.estynsoftware.cloud")
    assert (r.status_code, r.json()) == (403, {"error": "other_tenants_host"}) and not porth.asked


@pytest.mark.parametrize("context", [
    '{"environment":"porth-dau","tenant_id":"globex","trace_id":"t"}',          # names another tenant
    '{"environment":"porth-dau","tenant_id":"acme","trace_id":"t","extra":1}',  # not the shape porth-common reads
    "not json",
])
def test_a_link_whose_context_cannot_be_trusted_is_not_used(make, network_key, context):
    porth = FakePorth()
    r = post(make(linked(context=context), porth), assertion_for(network_key))
    assert r.status_code == 503 and not porth.asked


@pytest.mark.parametrize("code,status", [
    ("connector_not_enabled", 403), ("unmapped_role_claim", 403), ("role_exceeds_ceiling", 403),
    ("tenant_not_active", 403), ("duplicate_reference", 409), ("rate_limited", 429),
    ("host_credential_expired", 401), ("envelope_invalid:no_grant", 502), ("internal_error", 502),
])
def test_porths_answer_is_passed_on(make, network_key, code, status):
    r = post(make(linked(), FakePorth({"ok": False, "error": {"code": code}})), assertion_for(network_key))
    assert (r.status_code, r.json()) == (status, {"error": code})


def test_porth_not_answering(make, network_key):
    from supplier_portal import porth_session

    def unreachable(record, body):
        raise porth_session._Unreachable("timeout")

    r = post(make(linked(), unreachable), assertion_for(network_key))
    assert (r.status_code, r.json()) == (503, {"error": "porth_unavailable"})


def test_neither_the_session_nor_the_assertion_is_logged(make, network_key, caplog):
    caplog.set_level(logging.DEBUG)
    token = assertion_for(network_key)
    post(make(linked(), FakePorth()), token)
    assert SECRET_TOKEN not in caplog.text and token not in caplog.text
    assert "session_id=ses-1" in caplog.text


def test_an_unreadable_network_key_is_named_not_a_500(network_key, monkeypatch, caplog):
    """Found live: with the key parameter unreadable every request was a bare 500."""
    monkeypatch.setattr(web, "_KEY", None)
    monkeypatch.setenv("SUPPLIERLINK_PUBLIC_KEY_PARAMETER", "/ems/test/suppliers/supplierlink/public-key")

    def no_key():
        raise RuntimeError("ParameterNotFound")

    monkeypatch.setattr(web, "supplierlink_key", no_key)
    api = web.build()
    api.dependency_overrides[web.links] = lambda: OneLink(linked())
    r = TestClient(api, base_url=f"https://{HOST}").post("/suppliers/session", json={"assertion": "a.b.c"})
    assert (r.status_code, r.json()) == (503, {"error": "network_key_unavailable"})
    assert "/ems/test/suppliers/supplierlink/public-key" in caplog.text
