"""The request path — Phase B (PORTH-587).

These tests substitute two seams and nothing else:

* ``porth_common.director.get_context`` — the boundary that verifies the
  envelope. Substituting it is substituting KMS, which a unit test has no
  business calling. Every test therefore hands the Director the *exact* shape
  ``_service_context`` produces from verified claims, so the fake cannot flatter
  the code by being more generous than the real thing.
* ``FfugDirector.resource`` — the narrowed connection. What it returns here is a
  plain double; the narrowing it stands in for is IAM's, asserted against the
  template in ``test_template_isolation.py`` and witnessed live in UAT-3.

What is deliberately NOT faked: the refusal paths. Those are ffug's own logic
and run for real.
"""

from unittest.mock import MagicMock

import pytest
from porth_common.context.envelope import (
    EnvelopeAudienceMismatchError,
    EnvelopeEnvironmentMismatchError,
    EnvelopeExpiredError,
    EnvelopeMalformedError,
    EnvelopeSignatureInvalidError,
    EnvelopeUnsignedError,
)
from porth_common.internal_plane.config import ServiceSuspendedError, UnknownServiceError

from ffug import handler as h
from ffug import salt

ACME_PRIME = "11473776585539494943"
GLOBEX_PRIME = "9764321322338584621"


def verified_context(tenant_id="acme", environment="prod", source="porth"):
    """Exactly what porth_common builds from verified claims — no more.

    Note what is empty and stays empty: roles, permissions, and every user
    field. A service principal is not a human principal, so a permission check
    written for a person fails closed. Copying the real shape is the point.
    """
    return {
        "_boundary": "service",
        "tenant_id": tenant_id,
        "environment": environment,
        "source_service": source,
        "trace_id": "trace-1",
        "organization_id": "",
        "user_id": "",
        "external_id": "",
        "porth_user_id": "",
        "roles": "",
        "permissions": "",
        "user_email": "",
        "user_display_name": "",
        "user_first_name": "",
        "user_last_name": "",
        "user_avatar_url": "",
        "user_status": "",
        "user_created_at": "",
        "user_updated_at": "",
    }


@pytest.fixture
def table():
    return MagicMock()


@pytest.fixture
def porth(monkeypatch, table):
    """Wire both seams. Returns a controller the tests drive."""

    class Controller:
        context = verified_context()
        table = None

        def arrives_as(self, **kwargs):
            self.context = verified_context(**kwargs)

        def raises(self, exc):
            def boom(_event):
                raise exc

            monkeypatch.setattr("porth_common.director.get_context", boom)

        def tenant_is(self, status="active", prime=ACME_PRIME):
            row = {"status": status}
            if prime is not None:
                row["prime"] = prime
            self.table.get_item.return_value = {"Item": row}

        def tenant_is_unknown(self):
            self.table.get_item.return_value = {}

    controller = Controller()
    controller.table = table

    monkeypatch.setattr("porth_common.director.get_context", lambda _e: controller.context)
    monkeypatch.setattr(
        h.FfugDirector, "resource", lambda self, _capability: MagicMock(Table=lambda _n: table)
    )
    # The identity broker, for the probe. Faked for the same reason as the
    # resource above: what STS would answer is IAM's business, asserted against
    # the template and witnessed live, not something a unit test should call.
    monkeypatch.setattr(
        h.FfugDirector,
        "client",
        lambda self, _capability: MagicMock(
            get_caller_identity=lambda: {
                "Arn": "arn:aws:sts::1:assumed-role/ems-FfugTenantRole-ABC/porth-tenant"
            }
        ),
    )
    controller.tenant_is()
    return controller


def err(result):
    return result["error"]["code"]


# --- the tenant is not a payload field any more ------------------------------


def test_tenant_comes_from_the_verified_claims_not_the_payload(porth, table):
    """The keystone. A caller that names a tenant is ignored, not obeyed —
    ``tenant_id`` is simply not a field this handler reads."""
    porth.arrives_as(tenant_id="acme")

    h.handler({"operation": "echo", "item_id": "i-1", "payload": 1, "tenant_id": "globex",
               "environment": "somewhere-else"})

    assert table.put_item.call_args[1]["Item"]["pk"] == "ENV#prod#TENANT#acme"


def test_an_invocation_with_no_context_is_refused(porth):
    porth.context = {}

    assert err(h.handler({"operation": "hash", "payload": 1})) == "missing_context"
    assert err(h.handler({})) == "missing_context"
    assert err(h.handler(None)) == "missing_context"


# --- envelope rejection classes (UAT-4) --------------------------------------


@pytest.mark.parametrize(
    "exc,code",
    [
        (EnvelopeUnsignedError("no token"), "unsigned"),
        (EnvelopeSignatureInvalidError("forged"), "bad_signature"),
        (EnvelopeExpiredError("stale"), "expired"),
        (EnvelopeAudienceMismatchError("for someone else"), "audience_mismatch"),
        (EnvelopeEnvironmentMismatchError("wrong slot"), "environment_mismatch"),
        (EnvelopeMalformedError("garbage"), "malformed"),
    ],
)
def test_each_envelope_rejection_keeps_its_own_code(porth, table, exc, code):
    """The codes are the library's ``reason_code``, not ffug's invention, so
    ffug's replies and Porth's audit-log lines share one vocabulary."""
    porth.raises(exc)

    result = h.handler({"operation": "hash", "payload": 1})

    assert err(result) == code
    assert not table.put_item.called


@pytest.mark.parametrize(
    "exc", [UnknownServiceError("ghost"), ServiceSuspendedError("ghost", "suspended")]
)
def test_a_verified_envelope_from_an_unaccepted_service_is_its_own_fault(porth, exc):
    """Distinct from a bad signature on purpose: one is forgery, the other is
    configuration, and they want different people looking at them."""
    porth.raises(exc)

    assert err(h.handler({"operation": "hash", "payload": 1})) == "source_service_refused"


def test_a_narrowing_failure_is_not_answered_it_is_raised(porth, monkeypatch):
    """A deployment fault, not a caller fault. It must alarm as an invocation
    error rather than being handed back to the caller as a tidy rejection."""
    from porth_common.director import ResourceUnavailableError

    monkeypatch.setattr(
        h.FfugDirector, "resource", MagicMock(side_effect=RuntimeError("AssumeRole denied"))
    )

    with pytest.raises(ResourceUnavailableError):
        h.handler({"operation": "hash", "payload": 1})


# --- the tenant must have been provisioned by the bus ------------------------


def test_a_tenant_the_bus_has_not_announced_is_refused(porth):
    """ffug cannot mint its own salt. A caller arriving before the event is
    refused rather than served under an invented one."""
    porth.tenant_is_unknown()

    assert err(h.handler({"operation": "hash", "payload": 1})) == "tenant_not_provisioned"


def test_a_suspended_tenant_is_served_nothing(porth, table):
    """TS-MC.8 — refusal at event-delivery latency, not at cache TTL."""
    porth.tenant_is(status="suspended")

    assert err(h.handler({"operation": "hash", "payload": 1})) == "tenant_not_active"
    assert err(h.handler({"operation": "echo", "item_id": "i", "payload": 1})) == "tenant_not_active"
    assert err(h.handler({"operation": "get", "item_id": "i"})) == "tenant_not_active"
    assert not table.put_item.called


def test_a_deleted_tenants_stripped_marker_is_not_a_salt(porth):
    """Reached by a caller holding a still-valid envelope for a tenant deleted
    moments ago. The marker has a status and no salt; it must not be usable."""
    porth.tenant_is(status="deleted", prime=None)

    assert err(h.handler({"operation": "hash", "payload": 1})) == "tenant_not_active"


# --- hash: the demonstrable half --------------------------------------------


def test_hash_returns_this_tenants_digest_and_the_salt_behind_it(porth):
    result = h.handler({"operation": "hash", "payload": {"amount": 100}})

    assert result["ok"] is True
    assert result["prime"] == ACME_PRIME
    assert result["digest"] == salt.digest(ACME_PRIME, {"amount": 100})


def test_the_same_payload_under_two_tenants_gives_two_digests(porth):
    """The property the whole slice exists to show. Both invocations run the
    same code on the same input; only the salt each one is ALLOWED to read
    differs, and that permission is IAM's to grant."""
    porth.arrives_as(tenant_id="acme")
    porth.tenant_is(prime=ACME_PRIME)
    acme = h.handler({"operation": "hash", "payload": {"amount": 100}})

    porth.arrives_as(tenant_id="globex")
    porth.tenant_is(prime=GLOBEX_PRIME)
    globex = h.handler({"operation": "hash", "payload": {"amount": 100}})

    assert acme["digest"] != globex["digest"]


def test_hash_reads_the_salt_from_this_tenants_partition_only(porth, table):
    porth.arrives_as(tenant_id="globex")

    h.handler({"operation": "hash", "payload": 1})

    assert table.get_item.call_args[1]["Key"] == {
        "pk": "ENV#prod#TENANT#globex",
        "sk": "PROJECTION",
    }


def test_hash_writes_nothing(porth, table):
    """Kept pure so ``echo`` stays the only writer and the residue sweep stays
    a one-prefix question."""
    h.handler({"operation": "hash", "payload": 1})

    assert not table.put_item.called


def test_hash_requires_a_payload(porth):
    assert err(h.handler({"operation": "hash"})) == "missing_payload"


# --- echo and get, unchanged in contract, now on narrowed credentials --------


def test_echo_stores_under_the_tenant_partition_and_hands_the_payload_back(porth, table):
    result = h.handler({"operation": "echo", "item_id": "i-1", "payload": {"hello": "world"}})

    assert result == {"ok": True, "operation": "echo", "item_id": "i-1", "payload": {"hello": "world"}}
    item = table.put_item.call_args[1]["Item"]
    assert item == {"pk": "ENV#prod#TENANT#acme", "sk": "ITEM#i-1", "payload": {"hello": "world"}}


def test_echo_is_still_the_default_op(porth, table):
    h.handler({"item_id": "i-1", "payload": 1})

    assert table.put_item.called


def test_get_reads_back_under_the_same_keys(porth, table):
    table.get_item.side_effect = [
        {"Item": {"status": "active", "prime": ACME_PRIME}},
        {"Item": {"payload": {"hello": "world"}}},
    ]

    result = h.handler({"operation": "get", "item_id": "i-1"})

    assert result["payload"] == {"hello": "world"}
    assert table.get_item.call_args[1]["Key"] == {
        "pk": "ENV#prod#TENANT#acme",
        "sk": "ITEM#i-1",
    }


def test_get_missing_item_is_a_typed_rejection(porth, table):
    table.get_item.side_effect = [{"Item": {"status": "active", "prime": ACME_PRIME}}, {}]

    assert err(h.handler({"operation": "get", "item_id": "nope"})) == "not_found"


def test_echo_requires_item_id_and_payload(porth, table):
    assert err(h.handler({"operation": "echo", "payload": 1})) == "missing_item_id"
    assert err(h.handler({"operation": "echo", "item_id": "i-1"})) == "missing_payload"
    assert not table.put_item.called


def test_unknown_op_is_refused(porth, table):
    assert err(h.handler({"operation": "delete_everything"})) == "unknown_op"
    assert not table.put_item.called


# --- what the narrowed session can actually reach -----------------------------


DENIED = Exception("AccessDeniedException: User is not authorized to perform this action")


def narrowed_to(table, own_partition):
    """Make the double behave the way a narrowed session does.

    Not decoration. The earlier version of these tests let the double allow
    every read, which made three of the four attempts "succeed" and the probe
    report a breach it had invented. A fake that is more permissive than IAM
    tests nothing; this one refuses exactly what LeadingKeys refuses — any
    partition that is not the one the envelope named — and denies Scan outright
    because ffug is granted none.
    """
    table.scan.side_effect = DENIED

    def query(**kwargs):
        if kwargs["ExpressionAttributeValues"][":pk"] != own_partition:
            raise DENIED
        return {"Items": [], "Count": 0}

    table.query.side_effect = query


def test_the_probe_names_no_tenant_and_asks_only_about_its_own(porth, table):
    """The question behind the whole fixture, asked the strict way.

    The probe payload is empty — there is no tenant field, and adding one would
    change nothing because the handler does not read one. Every partition it
    queries is derived from the envelope, so a caller cannot aim this at anyone.
    """
    porth.arrives_as(tenant_id="globex")
    narrowed_to(table, "ENV#prod#TENANT#globex")

    result = h.handler({"operation": "isolation_probe"})

    assert result["tenant_id"] == "globex"
    queried = [
        call[1]["ExpressionAttributeValues"][":pk"] for call in table.query.call_args_list
    ]
    assert queried == [
        "ENV#prod#TENANT#globex",
        "ENV#prod#TENANT#__isolation_probe__",
        "ENV#__isolation_probe__#TENANT#globex",
    ]


def test_a_scan_is_expected_to_be_refused_not_filtered(porth, table):
    """The answer to "what do you get if we just scan the table?".

    Nothing — the attempt is refused outright, and that is the intended result
    rather than a gap. dynamodb:LeadingKeys binds to the key of the item being
    accessed and a scan names none, so the condition passes vacuously; a scan
    granted under it returns every tenant's rows. The isolation is that the
    question cannot be asked.
    """
    narrowed_to(table, "ENV#prod#TENANT#acme")

    result = h.handler({"operation": "isolation_probe"})
    scan = result["attempts"][0]

    assert scan["expect"] == "deny"
    assert scan["allowed"] is False
    assert scan["detail"] == "refused by IAM"
    assert result["isolated"] is True


def test_a_scan_that_succeeds_is_a_breach_and_says_how_wide(porth, table):
    """The guard on the test above, and the one that matters if Scan is ever
    granted "just for diagnostics".

    A scan does not fail loudly when it is wrongly permitted — it succeeds, and
    the damage is only visible in what came back. So the count of DISTINCT
    tenant partitions is carried on the result and the panel turns red on it.
    """
    narrowed_to(table, "ENV#prod#TENANT#acme")
    table.scan.side_effect = None
    table.scan.return_value = {
        "Items": [
            {"pk": "ENV#prod#TENANT#acme", "sk": "PROJECTION"},
            {"pk": "ENV#prod#TENANT#globex", "sk": "PROJECTION"},
        ],
        "Count": 2,
    }

    result = h.handler({"operation": "isolation_probe"})
    scan = result["attempts"][0]

    assert scan["allowed"] is True
    assert scan["partitions_seen"] == 2
    assert scan["pass"] is False
    assert result["isolated"] is False


def test_the_probe_reports_iam_not_provisioning(porth, table):
    """An unannounced tenant must not read as an isolation failure.

    ``_active_projection`` is deliberately not called: the probe answers what
    the credentials permit, and a tenant whose bus event has not arrived should
    see its own partition allowed and empty. Conflating the two is how an
    empty projection came to look like a broken consumer in the first place.
    """
    porth.tenant_is_unknown()
    narrowed_to(table, "ENV#prod#TENANT#acme")

    result = h.handler({"operation": "isolation_probe"})

    assert result["ok"] is True
    assert result["isolated"] is True
    assert result["attempts"][1]["allowed"] is True


def test_the_probe_writes_nothing(porth, table):
    narrowed_to(table, "ENV#prod#TENANT#acme")

    h.handler({"operation": "isolation_probe"})

    assert not table.put_item.called
    assert not table.delete_item.called
