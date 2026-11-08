"""Reading a SupplierLink assertion: each rule that keeps a forged or stale one out."""

import base64
import json

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from supplier_portal.assertion import Unverified, check, issue

NOW = 1_900_000_000


def claims(**changes):
    base = dict(iss="supplierlink", aud="ems-accounts", sub="c-41", jti="a-1", iat=NOW, exp=NOW + 120,
                buyer="buyer-acme", supplier="sup-globex", role="billing")
    base.update(changes)
    return {k: v for k, v in base.items() if v is not None}


def rejected(token, key, now=NOW):
    with pytest.raises(Unverified) as caught:
        check(token, public_key=key.public_key(), now=now)
    return caught.value.why


def test_a_valid_assertion_names_the_contact_supplier_buyer_and_role(network_key):
    contact = check(issue(claims(), private_key=network_key), public_key=network_key.public_key(), now=NOW)
    assert (contact.contact, contact.supplier, contact.buyer, contact.role) == ("c-41", "sup-globex", "buyer-acme", "billing")
    assert (contact.assertion_id, contact.valid_until, contact.connector) == ("a-1", NOW + 120, "supplierlink")


def test_signed_by_any_other_key(network_key):
    other = ec.generate_private_key(ec.SECP256R1())
    assert rejected(issue(claims(), private_key=other), network_key) == "signature"


def test_altered_after_signing(network_key):
    head, _, sig = issue(claims(), private_key=network_key).split(".")
    body = base64.urlsafe_b64encode(json.dumps(claims(supplier="sup-other")).encode()).rstrip(b"=").decode()
    assert rejected(f"{head}.{body}.{sig}", network_key) == "signature"


def test_any_algorithm_but_es256(network_key):
    good = issue(claims(), private_key=network_key)
    for alg in ("none", "HS256", "RS256"):
        head = base64.urlsafe_b64encode(json.dumps({"alg": alg}).encode()).rstrip(b"=").decode()
        assert rejected(f"{head}.{good.split('.', 1)[1]}", network_key) == "algorithm"


@pytest.mark.parametrize("token", ["", "x", "a.b", "a.b.c", "a.b.c.d", "not.an.assertion"])
def test_not_an_assertion(network_key, token):
    assert rejected(token, network_key) in {"shape", "encoding", "json"}


def test_expiry_with_slack(network_key):
    assert rejected(issue(claims(iat=NOW - 200, exp=NOW - 30), private_key=network_key), network_key) == "expired"
    assert check(issue(claims(iat=NOW - 125, exp=NOW - 5), private_key=network_key), public_key=network_key.public_key(), now=NOW)


def test_issued_ahead_of_the_clock(network_key):
    assert rejected(issue(claims(iat=NOW + 60, exp=NOW + 120), private_key=network_key), network_key) == "from_the_future"


def test_an_assertion_may_not_live_long(network_key):
    assert rejected(issue(claims(exp=NOW + 3600), private_key=network_key), network_key) == "too_long_lived"


@pytest.mark.parametrize("change,why", [
    (dict(iss="another-network"), "issuer"),
    (dict(aud="another-app"), "audience"),
    (dict(sub=None), "claim_sub"),
    (dict(jti=None), "claim_jti"),
    (dict(buyer=None), "claim_buyer"),
    (dict(supplier=""), "claim_supplier"),
    (dict(role="has spaces"), "claim_role"),
    (dict(iat="now"), "times"),
    (dict(sub="pat@globex.example"), "claim_sub_not_opaque"),
])
def test_each_claim(network_key, change, why):
    assert rejected(issue(claims(**change), private_key=network_key), network_key) == why
