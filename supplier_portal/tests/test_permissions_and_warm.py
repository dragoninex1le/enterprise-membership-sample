"""PORTH-658 (Porth 0.4.26): both claim-mapping routes, and warming the mint.

A SupplierLink assertion may carry a role, permissions, or both; the portal forwards
each exactly as signed and the buyer's mapping reads one. With PORTH_MINT_WARM=1 the
portal starts Porth's `warm` call for the HOST's tenant before it touches the assertion,
and the mint waits for it.
"""

import threading
import time

import pytest
from fastapi.testclient import TestClient

from supplier_portal import porth_session, web
from supplier_portal.assertion import Unverified, check, issue
from supplier_portal.links import BuyerLink

from test_session import CONTEXT, HOST, FakePorth, linked, post
from test_session import assertion_for as _assertion_for


def assertion_for(key, **changes):
    """As test_session's, but a claim given as None is left out, not signed as null."""
    if any(v is None for v in changes.values()):
        now = int(time.time())
        base = dict(iss="supplierlink", aud="ems-accounts", sub="c-41", jti=f"a-{time.monotonic_ns()}",
                    iat=now, exp=now + 120, buyer="buyer-acme", supplier="sup-globex", role="billing")
        base.update(changes)
        return issue({k: v for k, v in base.items() if v is not None}, private_key=key)
    return _assertion_for(key, **changes)

NOW = 1_900_000_000


def claims(**changes):
    base = dict(iss="supplierlink", aud="ems-accounts", sub="c-41", jti="a-1", iat=NOW, exp=NOW + 120,
                buyer="buyer-acme", supplier="sup-globex")
    base.update(changes)
    return {k: v for k, v in base.items() if v is not None}


def read(key, **changes):
    return check(issue(claims(**changes), private_key=key), public_key=key.public_key(), now=NOW)


def why(key, **changes):
    with pytest.raises(Unverified) as caught:
        read(key, **changes)
    return caught.value.why


# ── the assertion ──────────────────────────────────────────────────────────────

def test_an_assertion_may_carry_permissions_instead_of_a_role(network_key):
    contact = read(network_key, permissions=["invoices:submit", "invoices:view"])
    assert (contact.role, contact.permissions) == ("", ("invoices:submit", "invoices:view"))


def test_or_both(network_key):
    contact = read(network_key, role="billing", permissions=["invoices:view"])
    assert (contact.role, contact.permissions) == ("billing", ("invoices:view",))


def test_but_at_least_one(network_key):
    assert why(network_key) == "claim_role_or_permissions"


@pytest.mark.parametrize("permissions", [
    [], "invoices:view", ["ok", 7], [""], ["x" * 129], ["p"] * 257,
])
def test_permissions_outside_porths_bounds_are_refused(network_key, permissions):
    assert why(network_key, permissions=permissions) == "claim_permissions"


def test_permissions_at_porths_bounds_are_accepted(network_key):
    assert len(read(network_key, permissions=[f"p{i}" for i in range(256)]).permissions) == 256
    assert read(network_key, permissions=["x" * 128]).permissions == ("x" * 128,)


# ── what goes to Porth ─────────────────────────────────────────────────────────

@pytest.fixture
def make(network_key, monkeypatch):
    monkeypatch.setattr(web, "_KEY", network_key.public_key())

    def client(link=None, porth=None, warm=None, store=None):
        api = web.build()
        api.dependency_overrides[web.links] = lambda: store or Store(link)
        api.dependency_overrides[web.mint_transport] = lambda: porth
        api.dependency_overrides[web.warm_transport] = lambda: warm
        return TestClient(api, base_url=f"https://{HOST}")

    return client


class Store:
    def __init__(self, link=None, of_tenant=None):
        self.link = link
        self.tenants_asked = []
        self._of_tenant = of_tenant

    def find(self, buyer):
        return self.link if self.link and self.link.buyer == buyer else None

    def of_tenant(self, tenant):
        self.tenants_asked.append(tenant)
        if self._of_tenant is not None:
            return self._of_tenant(tenant)
        return [self.link] if self.link and self.link.tenant == tenant else []


def test_permissions_go_to_porth_verbatim_and_no_role_claim_when_none_was_signed(make, network_key):
    porth = FakePorth()
    signed = ["invoices:submit", "Invoices:View", "unknown.thing"]
    r = post(make(linked(), porth), assertion_for(network_key, role=None, permissions=signed))
    assert r.status_code == 200, r.text
    body = porth.asked[0][1]
    assert body["permission_claims"] == signed and "role_claim" not in body


def test_a_role_alone_sends_no_permission_claims(make, network_key):
    porth = FakePorth()
    post(make(linked(), porth), assertion_for(network_key))
    body = porth.asked[0][1]
    assert body["role_claim"] == "billing" and "permission_claims" not in body


def test_both_are_sent_when_both_are_signed(make, network_key):
    porth = FakePorth()
    post(make(linked(), porth), assertion_for(network_key, permissions=["invoices:view"]))
    body = porth.asked[0][1]
    assert (body["role_claim"], body["permission_claims"]) == ("billing", ["invoices:view"])


def test_no_role_for_permissions_is_a_403(make, network_key):
    porth = FakePorth({"ok": False, "error": {"code": "no_role_for_permissions"}})
    r = post(make(linked(), porth), assertion_for(network_key, role=None, permissions=["invoices:view"]))
    assert (r.status_code, r.json()) == (403, {"error": "no_role_for_permissions"})


# ── warming the mint ───────────────────────────────────────────────────────────

class Recorder:
    """One timeline across the warm call, the key read and the mint."""

    def __init__(self):
        self.events = []
        self.lock = threading.Lock()

    def note(self, what):
        with self.lock:
            self.events.append(what)


@pytest.fixture
def warming(monkeypatch):
    monkeypatch.setenv("PORTH_MINT_WARM", "1")


def test_off_by_default_nothing_is_sent(make, network_key, monkeypatch):
    monkeypatch.delenv("PORTH_MINT_WARM", raising=False)
    warm, porth = FakePorth({"ok": True}), FakePorth()
    store = Store(linked())
    assert post(make(porth=porth, warm=warm, store=store), assertion_for(network_key)).status_code == 200
    assert not warm.asked and not store.tenants_asked


def test_the_warm_call_starts_before_the_assertion_is_read_and_the_mint_waits_for_it(
        make, network_key, monkeypatch, warming):
    seen = Recorder()
    key = network_key.public_key()

    def slow_warm(record, body):
        seen.note("warm.start")
        time.sleep(0.3)
        seen.note("warm.end")
        return {"ok": True, "operation": "warm", "warmed": ["tenant"]}

    def read_key():
        seen.note("key.read")
        return key

    porth = FakePorth()

    def mint(record, body):
        seen.note("mint")
        return porth(record, body)

    monkeypatch.setattr(web, "supplierlink_key", read_key)
    r = post(make(linked(), mint, slow_warm), assertion_for(network_key))
    assert r.status_code == 200, r.text
    assert seen.events.index("warm.start") < seen.events.index("warm.end") < seen.events.index("mint")
    # The warm call was already running while the key was read and the assertion checked.
    assert seen.events.index("warm.start") < seen.events.index("mint")
    assert "key.read" in seen.events


def test_the_warm_call_names_the_hosts_tenant_and_the_connector(make, network_key, warming):
    warm = FakePorth({"ok": True})
    store = Store(linked())
    post(make(porth=FakePorth(), warm=warm, store=store), assertion_for(network_key))
    record, body = warm.asked[0]
    assert (record.tenant_id, body) == ("acme", {"connector_type": "supplierlink"})
    assert store.tenants_asked == ["acme"]  # the host's tenant, asked before anything was read


def test_the_warm_tenant_comes_from_the_host_never_the_assertion(make, network_key, warming):
    globex = BuyerLink(buyer="buyer-globex", tenant="globex",
                       porth_context=CONTEXT.replace("acme", "globex"), linked_by="pu-1", linked_at="t")
    warm = FakePorth({"ok": True})
    store = Store(globex)  # the assertion's buyer is linked to globex, the host is acme's
    r = post(make(porth=FakePorth(), warm=warm, store=store), assertion_for(network_key, buyer="buyer-globex"))
    assert store.tenants_asked == ["acme"] and not warm.asked  # acme holds no link: no warm call
    assert (r.status_code, r.json()) == (403, {"error": "other_tenants_host"})


def test_a_failing_warm_call_still_mints(make, network_key, warming):
    def broken(record, body):
        raise RuntimeError("Porth said no")

    porth = FakePorth()
    r = post(make(linked(), porth, broken), assertion_for(network_key))
    assert r.status_code == 200 and porth.asked


def test_a_refused_warm_call_still_mints(make, network_key, warming):
    porth = FakePorth()
    r = post(make(linked(), porth, FakePorth({"ok": False, "error": {"code": "body_invalid"}})),
             assertion_for(network_key))
    assert r.status_code == 200 and porth.asked


def test_a_warm_call_that_never_answers_is_waited_for_only_so_long(make, network_key, warming, monkeypatch):
    monkeypatch.setattr(porth_session, "WARM_WAIT_SECONDS", 0.2)
    release = threading.Event()

    def hung(record, body):
        release.wait(5)
        return {"ok": True}

    porth = FakePorth()
    started = time.monotonic()
    try:
        r = post(make(linked(), porth, hung), assertion_for(network_key))
        took = time.monotonic() - started
    finally:
        release.set()
    assert r.status_code == 200 and porth.asked and took < 2


def test_a_host_with_no_linked_buyer_sends_no_warm_call(make, network_key, warming):
    warm = FakePorth({"ok": True})
    r = post(make(None, FakePorth(), warm), assertion_for(network_key))
    assert (r.status_code, r.json()) == (403, {"error": "buyer_not_linked"}) and not warm.asked


def test_a_link_lookup_that_fails_sends_no_warm_call_and_still_mints(make, network_key, warming):
    def boom(tenant):
        raise RuntimeError("dynamodb")

    warm, porth = FakePorth({"ok": True}), FakePorth()
    r = post(make(porth=porth, warm=warm, store=Store(linked(), of_tenant=boom)), assertion_for(network_key))
    assert r.status_code == 200 and porth.asked and not warm.asked
