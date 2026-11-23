"""The simulator API signs logins the supplier portal accepts, and sends them to the right host.

The portal's own checker (supplier_portal.assertion.check) is the judge of the format, so
a change on either side that breaks the other fails here, not on a live slot.
"""

import pathlib
import sys

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "supplierlink_sim" / "src"))
sys.path.insert(0, str(ROOT / "supplier_portal"))

import app  # noqa: E402
from supplier_portal import assertion  # noqa: E402

KEY = ec.generate_private_key(ec.SECP256R1())
FORM = {"tenant": "ems-test", "buyer": "buyer-ems-test", "supplier": "proof-sup-a",
        "contact": "contact-a", "method": "role", "role": "billing",
        "permissions": "invoices:submit, invoices:view"}
client = TestClient(app.app)


@pytest.fixture(autouse=True)
def signing_key(monkeypatch):
    monkeypatch.setattr(app, "_private_key", KEY)
    monkeypatch.setattr(app, "API_APEX", "porth-dau.ems.estynsoftware.cloud")


def test_a_role_login_is_accepted_by_the_portal():
    contact = assertion.check(app.sign(app.claims(app.SignIn(**FORM))), public_key=KEY.public_key())
    assert (contact.buyer, contact.supplier, contact.contact, contact.role) == \
        ("buyer-ems-test", "proof-sup-a", "contact-a", "billing")
    assert contact.permissions == ()


def test_a_permissions_login_is_accepted_by_the_portal():
    form = app.SignIn(**{**FORM, "method": "permissions"})
    contact = assertion.check(app.sign(app.claims(form)), public_key=KEY.public_key())
    assert contact.permissions == ("invoices:submit", "invoices:view")
    assert contact.role == ""


def test_every_login_is_new():
    form = app.SignIn(**FORM)
    assert app.claims(form)["jti"] != app.claims(form)["jti"]


@pytest.mark.parametrize("missing", ["tenant", "buyer", "supplier", "contact", "role"])
def test_a_missing_field_is_refused_and_nothing_is_sent(monkeypatch, missing):
    monkeypatch.setattr(app, "post", lambda *a: pytest.fail("sent"))
    reply = client.post("/login", json={**FORM, missing: ""})
    assert reply.status_code == 400 and reply.json() == {"detail": f"{missing} is required"}


def test_empty_permissions_are_refused(monkeypatch):
    monkeypatch.setattr(app, "post", lambda *a: pytest.fail("sent"))
    reply = client.post("/login", json={**FORM, "method": "permissions", "permissions": " , "})
    assert reply.status_code == 400 and reply.json() == {"detail": "permissions is empty"}


def test_login_posts_to_the_tenants_session_route(monkeypatch):
    sent = {}

    def fake_post(url, body):
        sent.update(url=url, body=body)
        return 200, {"token": "prth_x", "session_id": "s", "expires_at": 1}

    monkeypatch.setattr(app, "post", fake_post)
    reply = client.post("/login", json=FORM)
    assert sent["url"] == "https://ems-test.api.porth-dau.ems.estynsoftware.cloud/suppliers/session"
    assert assertion.check(sent["body"]["assertion"], public_key=KEY.public_key()).role == "billing"
    answer = reply.json()
    assert reply.status_code == 200 and answer["status"] == 200 and answer["answer"]["token"] == "prth_x"
    assert isinstance(answer["ems_ms"], int)


def test_a_refusal_from_ems_is_shown_as_is(monkeypatch):
    monkeypatch.setattr(app, "post", lambda url, body: (403, {"error": "unmapped_role_claim"}))
    answer = client.post("/login", json=FORM).json()
    assert answer["status"] == 403 and answer["answer"] == {"error": "unmapped_role_claim"}


def test_the_lambda_entry_serves_an_http_api_event(monkeypatch):
    monkeypatch.setattr(app, "post", lambda url, body: (200, {}))
    event = {"version": "2.0", "routeKey": "POST /login", "rawPath": "/login", "rawQueryString": "",
             "headers": {"content-type": "application/json"}, "body": '{"tenant": ""}',
             "isBase64Encoded": False,
             "requestContext": {"http": {"method": "POST", "path": "/login", "sourceIp": "1.1.1.1",
                                         "protocol": "HTTP/1.1"}, "stage": "$default"}}
    assert app.handler(event, None)["statusCode"] == 400


def test_the_api_describes_itself():
    assert "/login" in client.get("/openapi.json").json()["paths"]
    assert client.get("/docs").status_code == 200
