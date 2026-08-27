"""The receiving end: verify, recompute, compare — and refuse in that order.

Two seams are substituted and nothing else, matching ffug's test module exactly:

* ``porth_common.director.get_context`` — the boundary that verifies the
  envelope. Substituting it substitutes KMS, which a unit test has no business
  calling. Every test hands the Director the shape a verified service context
  really has, so the fake cannot flatter the code by being more generous.
* ``CallbackDirector.resource`` — the narrowed connection, whose narrowing is
  IAM's and is asserted against the template.

What is deliberately NOT faked is ``verify_callback``. The correlation check is
the property this whole story turns on, and a test that stubbed it would assert
that the call site calls it rather than that a mismatched callback is refused.
It runs for real here, against real hashes.
"""

import pathlib
import sys
from unittest.mock import MagicMock

import pytest
from porth_common.context.correlation import context_hash
from porth_common.context.envelope import EnvelopeSignatureInvalidError
from porth_common.protocols.signing import Direction

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from sample_app_callback import handler as h  # noqa: E402

ENVIRONMENT = "prod"
TENANT = "acme"
TRACE = "trace-async-1"
PRIME = "11473776585539494943"
DIGEST = "a" * 64


def service_context(tenant_id=TENANT, environment=ENVIRONMENT, source="ffug", trace=TRACE):
    """A verified SERVICE context — every user field empty, because a service
    principal is not a human one and a permission check written for a person
    must fail closed rather than find something plausible."""
    return {
        "_boundary": "service",
        "tenant_id": tenant_id,
        "environment": environment,
        "source_service": source,
        "trace_id": trace,
        "organization_id": "", "user_id": "", "external_id": "", "porth_user_id": "",
        "roles": "", "permissions": "", "user_email": "", "user_display_name": "",
        "user_first_name": "", "user_last_name": "", "user_avatar_url": "",
        "user_status": "", "user_created_at": "", "user_updated_at": "",
    }


def expected_hash(environment=ENVIRONMENT, tenant_id=TENANT, trace=TRACE):
    """What the app stored at initiation.

    `source_service` is the INITIATOR's id, which is what the callback's
    verified `aud` names — and it is `ffug`, because the initiator and this
    ingress are the same service (Richard, 2026-08-27). The app is ffug's front
    half; there is no `sample-app` on the internal plane to anchor a hash to.

    That both ends now spell it the same way is the whole property: the app
    commits this hash before the work is requested, and verify_callback
    recomputes it from the token's audience. One string, computed twice, in two
    processes that never exchange it.
    """
    return context_hash(
        environment=environment, tenant_id=tenant_id,
        source_service="ffug", trace_id=trace,
    )


def record(*, trace=TRACE, correlation=None, record_id="i-1"):
    return {
        "pk": f"ENV#{ENVIRONMENT}#TENANT#{TENANT}",
        "sk": f"INVOICE#{record_id}",
        "invoice_id": record_id,
        "customer_name": "Globex",
        "amount": "98.0",
        "status": "approved",
        "fingerprint_status": "queued",
        "fingerprint_trace_id": trace,
        "fingerprint_correlation_hash": (
            expected_hash() if correlation is None else correlation
        ),
    }


@pytest.fixture
def porth(monkeypatch):
    """Wire both seams. Returns a controller the tests drive."""
    monkeypatch.setenv("PORTH_SERVICE_ID", "ffug")
    monkeypatch.setenv("PORTH_ENVIRONMENT", "dev")

    table = MagicMock()

    class Controller:
        context = service_context()
        table = None
        #: What `get_context` was asked for. The direction wall lives inside the
        #: library, so what a unit test CAN assert is that this ingress declares
        #: which side of it it is on — see the direction test below.
        asked_for = None

        def arrives_as(self, **kwargs):
            self.context = service_context(**kwargs)

        def raises(self, exc):
            def boom(_event, *_args, **_kwargs):
                raise exc

            monkeypatch.setattr("porth_common.director.get_context", boom)

        def holds(self, *items):
            # Two queries, one per approvable prefix: invoices then bills.
            self.table.query.side_effect = [{"Items": list(items)}, {"Items": []}]

    controller = Controller()
    controller.table = table

    def fake_get_context(_event, direction=None, *_args, **_kwargs):
        controller.asked_for = direction
        return controller.context

    monkeypatch.setattr("porth_common.director.get_context", fake_get_context)
    monkeypatch.setattr(
        h.CallbackDirector, "resource", lambda self, _capability: MagicMock(
            Table=lambda _n: table
        )
    )
    controller.holds(record())
    table.update_item.return_value = {"Attributes": record()}
    return controller


def event(payload=None, operation="fingerprint-complete"):
    return {"operation": operation, "payload": payload if payload is not None else
            {"prime": PRIME, "digest": DIGEST}}


def err(result):
    return result["error"]["code"]


# --- the direction wall ------------------------------------------------------


def test_this_door_declares_that_it_accepts_responses_only(porth):
    """The second half of PORTH-623, and the reason ffug can hold a signing key
    at all without becoming able to originate work.

    ffug holds a RESPONSE key and no request key. This ingress accepts response
    direction and nothing else, so the route cannot be used to start work — the
    pairing is what makes the callback safe, and either half alone does not.
    """
    h.handler(event())

    assert porth.asked_for is Direction.RESPONSE


def test_verify_callback_refuses_an_ingress_that_forgot_to_say_so(porth, monkeypatch):
    """Belt and braces from the library's side, asserted here because it is the
    guard that catches this file being changed rather than the library."""
    monkeypatch.setattr(
        h.CallbackDirector, "__init__",
        lambda self, e, c=None, **kw: h.Director.__init__(self, e, c),
    )

    assert err(h.handler(event())) == "callback_error"


# --- order: verify, then correlate -------------------------------------------


def test_a_badly_signed_callback_is_a_signature_failure_not_a_mismatch(porth):
    """Different events, different alarms.

    A forgery reported as a correlation mismatch sends whoever is holding the
    pager to look at bookkeeping. The ordering that prevents it is structural:
    the signature is checked as a precondition of the Director existing, so
    there is no path to the correlation check that skips it.
    """
    porth.raises(EnvelopeSignatureInvalidError("signature does not verify"))

    assert err(h.handler(event())) == "bad_signature"
    assert not porth.table.query.called, "the table was consulted before verification"


def test_an_authentic_callback_for_work_we_did_not_start_is_refused(porth):
    """The negative test PORTH-621 requires.

    Everything about this callback is genuine: signed by a registered service,
    addressed to us, naming a tenant we serve. What does not match is the
    context it claims to complete. That is a registered service completing work
    against a context this app never started — worth its own reason code and its
    own alarm, and never to be confused with a forgery.
    """
    porth.holds(record(correlation=expected_hash(tenant_id="globex")))

    result = h.handler(event())

    assert err(result) == "correlation_mismatch"
    assert not porth.table.update_item.called, "a mismatched callback still wrote"


def test_a_completion_nobody_is_waiting_for_is_refused(porth):
    """Authentic and unattributable — which is what a replayed completion looks
    like once the first one has landed and cleared the queued state."""
    porth.holds(record(trace="some-other-trace"))

    assert err(h.handler(event())) == "no_pending_work"


# --- what the callback may and may not decide --------------------------------


def test_the_completion_cannot_name_the_record_it_completes(porth):
    """The address is a trace this app minted and stored, never a record id the
    caller supplies.

    If ffug could name the row, a completing service could aim an authentic
    completion at a different record within the tenant. That whole class is
    removed rather than validated: these fields are simply not read.
    """
    porth.holds(record(record_id="i-1"))

    h.handler(event({"prime": PRIME, "digest": DIGEST,
                     "record_id": "i-99", "record_type": "bill"}))

    assert porth.table.update_item.call_args[1]["Key"]["sk"] == "INVOICE#i-1"


def test_the_tenant_comes_from_the_verified_claims(porth):
    """A callback cannot choose whose partition it writes to. There is no field
    for it, and the credentials underneath would refuse anyway."""
    porth.arrives_as(tenant_id="globex")
    porth.holds(record(correlation=expected_hash(tenant_id="globex")))

    h.handler(event())

    assert porth.table.update_item.call_args[1]["Key"]["pk"] == "ENV#prod#TENANT#globex"


def test_a_completion_carrying_no_result_is_refused(porth):
    """A blank digest written over a queued state would read as a finished
    fingerprint of nothing."""
    assert err(h.handler(event({"prime": PRIME}))) == "incomplete_result"
    assert not porth.table.update_item.called


def test_the_answer_lands_on_the_record_and_completes_it(porth):
    result = h.handler(event())

    assert result["ok"] is True
    values = porth.table.update_item.call_args[1]["ExpressionAttributeValues"]
    assert values[":p"] == PRIME
    assert values[":d"] == DIGEST
    assert values[":s"] == "complete"


def test_an_unknown_operation_is_refused_rather_than_defaulted(porth):
    """This ingress has one job. `echo`-style tolerance on a route that writes
    verified evidence is a route that does something unintended."""
    assert err(h.handler(event(operation="anything-else"))) == "unknown_op"
    assert err(h.handler({})) == "unknown_op"


def test_a_match_is_stated_not_inferred_from_silence(porth, caplog):
    """PORTH-622 AC3: the correlation match has to be VISIBLE.

    Before this, a mismatch logged a refusal and a match logged nothing, so
    "the check passed" was something a reader inferred from the absence of a
    line. That is the same shape that kept this app's whole log stream muted for
    four stories — an empty log group reads as quiet, not as silenced.
    """
    import logging

    with caplog.at_level(logging.INFO):
        result = h.handler(event())

    assert result["ok"] is True
    correlated = [r for r in caplog.records if "callback.correlated" in r.getMessage()]
    assert correlated, "a matching callback said nothing about the match"
    assert TRACE in correlated[0].getMessage(), "the line omits the trace a reader greps"


def test_a_refused_callback_makes_no_claim_about_correlation(porth, caplog):
    """The other half. The line must not be emitted on a path that did not match,
    or it stops being evidence and becomes decoration."""
    import logging

    porth.holds(record(correlation=expected_hash(tenant_id="globex")))

    with caplog.at_level(logging.INFO):
        assert err(h.handler(event())) == "correlation_mismatch"

    assert not [r for r in caplog.records if "callback.correlated" in r.getMessage()]
