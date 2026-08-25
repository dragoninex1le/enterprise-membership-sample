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

import json
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
        store = None

        def arrives_as(self, **kwargs):
            self.context = verified_context(**kwargs)

        def raises(self, exc):
            # Two parameters, because get_context gained `direction` in
            # porth-common 0.0.11 (PORTH-623) — the ingress declares which
            # direction it accepts so a response-direction kid presented at a
            # request door is refused inside the library. Defaulted so the stub
            # works whichever way the Director calls it.
            def boom(_event, _direction=None):
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

    # NOTE: stubbing get_context also stubs out the direction wall it now
    # enforces. That is the right trade here — these tests are about ffug's own
    # logic, and the wall is porth-common's to prove — but it means no test in
    # this file would notice if ffug's ingress started accepting the wrong
    # direction. ffug takes the default (`expects=REQUEST`), which is correct
    # for a request ingress; a callback ingress must pass Direction.RESPONSE.
    monkeypatch.setattr(
        "porth_common.director.get_context",
        lambda _e, _direction=None: controller.context,
    )
    store = MagicMock(Table=lambda _n: table)
    controller.store = store
    monkeypatch.setattr(h.FfugDirector, "resource", lambda self, _capability: store)
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


def attempt(result, needle):
    """The probe row whose description contains *needle*.

    By description, never by index. These were indexed until a fifth probe was
    inserted in the middle: two assertions broke, and a third kept passing
    against a different row that happened to expect the same outcome. A test
    that survives by coincidence is worse than one that fails.
    """
    matches = [
        a for a in result["attempts"]
        if a["attempt"] == needle or needle in a["attempt"]
    ]
    exact = [a for a in matches if a["attempt"] == needle]
    if exact:
        # 'query ENV#…#TENANT#acme' is a substring of the sibling probe's
        # 'query ENV#…#TENANT#acme-probe'. Prefer the exact row rather than
        # making every caller invent a longer needle.
        return exact[0]
    assert len(matches) == 1, f"{needle!r} matched {len(matches)} attempts"
    return matches[0]


def narrowed_to(table, own_partition, store=None):
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

    def batch_get_item(*, RequestItems):
        # ForAllValues over every key in the batch: one foreign key refuses the
        # whole request. Modelled rather than assumed, because "the batch came
        # back with only my rows" is the outcome IAM does NOT produce and a
        # lenient double would invent it.
        for spec in RequestItems.values():
            for key in spec["Keys"]:
                if key["pk"] != own_partition:
                    raise DENIED
        return {"Responses": {}}

    if store is not None:
        store.batch_get_item = batch_get_item


def test_the_probe_names_no_tenant_and_asks_only_about_its_own(porth, table):
    """The question behind the whole fixture, asked the strict way.

    The probe payload is empty — there is no tenant field, and adding one would
    change nothing because the handler does not read one. Every partition it
    queries is derived from the envelope, so a caller cannot aim this at anyone.
    """
    porth.arrives_as(tenant_id="globex")
    narrowed_to(table, "ENV#prod#TENANT#globex", porth.store)

    result = h.handler({"operation": "isolation_probe"})

    assert result["tenant_id"] == "globex"
    queried = [
        call[1]["ExpressionAttributeValues"][":pk"] for call in table.query.call_args_list
    ]
    assert queried == [
        "ENV#prod#TENANT#globex",
        "ENV#prod#TENANT#__isolation_probe__",
        "ENV#prod#TENANT#globex-probe",
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
    narrowed_to(table, "ENV#prod#TENANT#acme", porth.store)

    result = h.handler({"operation": "isolation_probe"})
    scan = attempt(result, "scan the whole table")

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
    narrowed_to(table, "ENV#prod#TENANT#acme", porth.store)
    table.scan.side_effect = None
    table.scan.return_value = {
        "Items": [
            {"pk": "ENV#prod#TENANT#acme", "sk": "PROJECTION"},
            {"pk": "ENV#prod#TENANT#globex", "sk": "PROJECTION"},
        ],
        "Count": 2,
    }

    result = h.handler({"operation": "isolation_probe"})
    scan = attempt(result, "scan the whole table")

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
    narrowed_to(table, "ENV#prod#TENANT#acme", porth.store)

    result = h.handler({"operation": "isolation_probe"})

    assert result["ok"] is True
    assert result["isolated"] is True
    assert attempt(result, "query ENV#prod#TENANT#acme")["allowed"] is True


def test_the_probe_writes_nothing(porth, table):
    narrowed_to(table, "ENV#prod#TENANT#acme", porth.store)

    h.handler({"operation": "isolation_probe"})

    assert not table.put_item.called
    assert not table.delete_item.called


def test_one_foreign_key_in_a_batch_refuses_the_whole_request(porth, table):
    """The Director test at its sharpest.

    Two separate queries differ in their whole request. These differ in ONE
    key, and FfugTenantRole's ceiling allows ENV#*#TENANT#* — every tenant — so
    an unnarrowed or wrongly-narrowed session would be allowed both. The
    refusal is attributable to the session policy and to nothing else.
    """
    narrowed_to(table, "ENV#prod#TENANT#acme", porth.store)

    batch = attempt(h.handler({"operation": "isolation_probe"}), "batch-get")

    assert batch["allowed"] is False
    assert batch["detail"] == "refused by IAM"
    assert batch["pass"] is True


def test_a_batch_that_answers_partially_fails_the_probe(porth, table):
    """IAM refuses the request; it does not quietly return the readable half.

    A result carrying only this tenant's row would mean something OTHER than
    IAM did the filtering — application code, or a policy that bound nothing —
    and that is exactly the comfortable-looking outcome this probe exists to
    catch. Also covers the Responses/{table} shape, which reports zero rows if
    it is read as though it were a Query.
    """
    narrowed_to(table, "ENV#prod#TENANT#acme", porth.store)
    porth.store.batch_get_item = lambda **_: {
        "Responses": {"porth-ffug-dev": [{"pk": "ENV#prod#TENANT#acme", "sk": "PROJECTION"}]}
    }

    result = h.handler({"operation": "isolation_probe"})
    batch = attempt(result, "batch-get")

    assert batch["allowed"] is True
    assert batch["partitions_seen"] == 1
    assert batch["pass"] is False
    assert result["isolated"] is False


def test_a_prefix_extension_of_this_tenant_is_refused(porth, table):
    """'acme' must not reach 'acme-staging'.

    A LeadingKeys pattern written TENANT#$tenant* rather than the exact key
    plus TENANT#$tenant#* admits exactly this, and PORTH-593 found that fault
    in Porth's own policy — so it is a regression probe, not a hypothetical.
    """
    narrowed_to(table, "ENV#prod#TENANT#acme", porth.store)

    sibling = attempt(h.handler({"operation": "isolation_probe"}), "acme-probe")

    assert sibling["expect"] == "deny"
    assert sibling["allowed"] is False


def test_a_named_real_tenant_is_probed_and_refused(porth, table):
    """The negative test aimed at a partition that actually holds data.

    Every other refusal here targets a tenant invented for the purpose. IAM
    denies on the key before consulting data, so those are honest — but they
    cannot tell a reader "refused" from "empty anyway". Naming a real tenant
    can.
    """
    narrowed_to(table, "ENV#prod#TENANT#acme", porth.store)

    result = h.handler({"operation": "isolation_probe", "probe_tenant": "globex"})
    named = attempt(result, "a real tenant")

    assert result["probe_tenant"] == "globex"
    assert named["attempt"].startswith("query ENV#prod#TENANT#globex")
    assert named["allowed"] is False
    assert result["isolated"] is True


def test_naming_your_own_tenant_adds_no_probe(porth, table):
    """It would assert 'deny' against the one partition that must be allowed,
    and fail the whole strip on a typo."""
    narrowed_to(table, "ENV#prod#TENANT#acme", porth.store)

    result = h.handler({"operation": "isolation_probe", "probe_tenant": "acme"})

    assert not [a for a in result["attempts"] if "a real tenant" in a["attempt"]]
    assert result["isolated"] is True


def test_the_probe_never_returns_rows_only_counts(porth, table):
    """If isolation IS broken, this endpoint must not become the reader.

    Every attempt reports an outcome, a row count and a count of distinct
    tenant partitions. No item body is carried, so even the failing case
    reports the breach without widening it.
    """
    narrowed_to(table, "ENV#prod#TENANT#acme", porth.store)
    table.query.side_effect = None
    table.query.return_value = {
        "Items": [{"pk": "ENV#prod#TENANT#globex", "sk": "PROJECTION", "prime": "7"}],
        "Count": 1,
    }

    result = h.handler({"operation": "isolation_probe", "probe_tenant": "globex"})

    assert "7" not in json.dumps(result)
    assert "prime" not in json.dumps(result)
    assert result["isolated"] is False


def test_everything_denied_is_a_failure_not_a_clean_sweep(porth, table):
    """The vacuous-pass guard.

    Five of the six rows pass BY being refused, so a wrong table name, a broken
    role or no narrowing at all would render as a perfect score. The allow row
    is what stops that, and this is the test that keeps it load-bearing.
    """
    table.scan.side_effect = DENIED
    table.query.side_effect = DENIED
    porth.store.batch_get_item = MagicMock(side_effect=DENIED)

    result = h.handler({"operation": "isolation_probe"})

    assert result["isolated"] is False
    assert attempt(result, "query ENV#prod#TENANT#acme")["pass"] is False


# --- PORTH-605: what the service says about itself ---------------------------


def test_no_log_line_at_any_level_carries_the_salt(porth, table, caplog):
    """The one assertion that must not be left to the log LEVEL.

    This repo's Actions logs are world-readable (PORTH-533) and CloudWatch
    outlives the request either way. The prime is returned to the approver on
    purpose — that is a different audience from a log line, and the standing
    rule is identifiers only.

    Runs at DEBUG deliberately: a rule that only holds at the default level is
    not a rule, it is a coincidence.
    """
    narrowed_to(table, "ENV#prod#TENANT#acme", porth.store)
    with caplog.at_level("DEBUG", logger="ffug.handler"):
        h.handler({"operation": "hash", "payload": {"amount": 100}})
        h.handler({"operation": "isolation_probe"})

    # getMessage() already interpolates; applying % again double-formats and
    # raises on the first line that has more args than placeholders left.
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert ACME_PRIME not in logged, "the salt reached a log line"
    assert "100" not in logged, "the payload body reached a log line"


def test_debug_shows_the_call_surviving_verification(porth, table, caplog):
    """The pair a reader actually wants: what ARRIVED, then what SURVIVED.

    `ffug.received` is emitted before the Director exists, so nothing in it is
    trusted — it reports the shape of the invocation. `ffug.verified` is emitted
    after, so every field in it is a signed claim.
    """
    narrowed_to(table, "ENV#prod#TENANT#acme", porth.store)
    with caplog.at_level("DEBUG", logger="ffug.handler"):
        h.handler({"operation": "hash", "payload": 1})

    lines = [r.getMessage() for r in caplog.records]
    assert any(line.startswith("ffug.received operation=hash") for line in lines)
    assert any("ffug.verified" in line and "tenant_id=acme" in line for line in lines)
    assert any("ffug.projection" in line and "has_salt=True" in line for line in lines)


def test_the_probe_verdict_is_visible_without_turning_debug_on(porth, table, caplog):
    """A regression in the boundary should be findable in the log stream, not
    only by reading a response body someone has to think to look at."""
    narrowed_to(table, "ENV#prod#TENANT#acme", porth.store)
    with caplog.at_level("INFO", logger="ffug.handler"):
        h.handler({"operation": "isolation_probe"})

    lines = [r.getMessage() for r in caplog.records]
    verdict = [line for line in lines if line.startswith("ffug.probe")]
    assert verdict and "isolated=True" in verdict[0], lines
