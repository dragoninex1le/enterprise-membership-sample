"""The simulator signs logins the supplier portal accepts, and sends them to the right host.

The portal's own checker (supplier_portal.assertion.check) is the judge of the format, so
a change on either side that breaks the other fails here, not on a live slot.
"""

import base64
import json
import pathlib
import sys

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "supplierlink_sim" / "src"))
sys.path.insert(0, str(ROOT / "supplier_portal"))

import app  # noqa: E402
from supplier_portal import assertion  # noqa: E402

KEY = ec.generate_private_key(ec.SECP256R1())
FORM = {"tenant": "ems-test", "buyer": "buyer-ems-test", "supplier": "proof-sup-a",
        "contact": "contact-a", "method": "role", "role": "billing",
        "permissions": "invoices:submit, invoices:view"}


@pytest.fixture(autouse=True)
def signing_key(monkeypatch):
    monkeypatch.setattr(app, "_private_key", KEY)
    monkeypatch.setattr(app, "API_APEX", "porth-dau.ems.estynsoftware.cloud")


def test_a_role_login_is_accepted_by_the_portal():
    contact = assertion.check(app.sign(app.claims(FORM)), public_key=KEY.public_key())
    assert (contact.buyer, contact.supplier, contact.contact, contact.role) == \
        ("buyer-ems-test", "proof-sup-a", "contact-a", "billing")
    assert contact.permissions == ()


def test_a_permissions_login_is_accepted_by_the_portal():
    contact = assertion.check(app.sign(app.claims({**FORM, "method": "permissions"})),
                              public_key=KEY.public_key())
    assert contact.permissions == ("invoices:submit", "invoices:view")
    assert contact.role == ""


def test_every_login_is_new():
    assert app.claims(FORM)["jti"] != app.claims(FORM)["jti"]


@pytest.mark.parametrize("missing", ["tenant", "buyer", "supplier", "contact", "role"])
def test_a_missing_field_is_said_and_nothing_is_sent(monkeypatch, missing):
    monkeypatch.setattr(app, "post", lambda *a: pytest.fail("sent"))
    answer = call("POST", "/login", {**FORM, missing: ""})
    assert answer == {"error": f"{missing} is required"}


def test_login_posts_to_the_tenants_session_route(monkeypatch):
    sent = {}

    def fake_post(url, body):
        sent.update(url=url, body=body)
        return 200, {"token": "prth_x", "session_id": "s", "expires_at": 1}

    monkeypatch.setattr(app, "post", fake_post)
    answer = call("POST", "/login", FORM)
    assert sent["url"] == "https://ems-test.api.porth-dau.ems.estynsoftware.cloud/suppliers/session"
    assert assertion.check(sent["body"]["assertion"], public_key=KEY.public_key()).role == "billing"
    assert answer["status"] == 200 and answer["answer"]["token"] == "prth_x"
    assert isinstance(answer["ems_ms"], int)


def test_a_refusal_from_ems_is_shown_as_is(monkeypatch):
    monkeypatch.setattr(app, "post", lambda url, body: (403, {"error": "unmapped_role_claim"}))
    answer = call("POST", "/login", FORM)
    assert answer["status"] == 403 and answer["answer"] == {"error": "unmapped_role_claim"}


def test_a_base64_body_is_read(monkeypatch):
    monkeypatch.setattr(app, "post", lambda url, body: (200, {}))
    event = request("POST", "/login", FORM)
    event.update(body=base64.b64encode(event["body"].encode()).decode(), isBase64Encoded=True)
    assert json.loads(app.handler(event, None)["body"])["status"] == 200


def test_the_page_has_every_control_a_test_drives():
    response = app.handler(request("GET", "/"), None)
    assert response["statusCode"] == 200
    for control in ("signin.form.tenant", "signin.form.buyer", "signin.form.supplier", "signin.form.contact",
                    "signin.form.by-role", "signin.form.by-permissions", "signin.form.role",
                    "signin.form.permissions", "signin.form.sign-in", "signin.result.status",
                    "signin.result.ems-ms", "signin.result.token", "signin.result.answer"):
        assert f'data-prawfid="{control}"' in response["body"]


def test_anything_else_is_not_found():
    assert app.handler(request("GET", "/other"), None)["statusCode"] == 404


def request(method, path, body=None):
    return {"requestContext": {"http": {"method": method}}, "rawPath": path,
            "body": json.dumps(body) if body is not None else None}


def call(method, path, body):
    return json.loads(app.handler(request(method, path, body), None)["body"])
