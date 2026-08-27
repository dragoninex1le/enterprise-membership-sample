"""The asynchronous half: what is queued, and what the drainer does with it.

Two properties carry this design, and both are the kind that keep working while
having quietly stopped being true:

* **the envelope never rides the queue** — what is persisted is a context, which
  needs no signature because only ffug's verified ingress writes where it lives;
* **a refused record is a batch item failure**, never a silent delete.
"""

import json
from unittest.mock import MagicMock

import pytest

from ffug import handler as h
from ffug import worker as w
# The two seams are wired exactly as the request-path tests wire them — same
# fixtures, imported rather than re-declared, so the async op cannot quietly
# be tested against a friendlier double than `hash` is.
from ffug.tests.test_handler import (  # noqa: F401
    ACME_PRIME,
    call,
    porth,
    table,
    verified_context,
)


# An operation and the CALLER'S OWN address (PORTH-624). Porth's registry holds
# no callback addresses, so the requester states where it listens; ffug relays
# it untouched. Note it is deliberately not `alpha`'s registered anything —
# there is nothing to register it against.
CALLBACK = {
    "operation": "fingerprint-complete",
    "endpoint": {"mode": "invoke", "target": "alpha-callback"},
}


@pytest.fixture
def queue(monkeypatch):
    """ffug's own queue. boto3 directly and not through the Director, because a
    queue inside a service is its own infrastructure — there is no Porth
    capability for one, deliberately."""
    client = MagicMock()
    monkeypatch.setattr(h, "WORK_QUEUE_URL", "https://sqs.test/queue")
    monkeypatch.setattr(h, "_queue", lambda: client)
    return client


def _sent(queue):
    return json.loads(queue.send_message.call_args[1]["MessageBody"])


def test_the_queued_message_carries_no_token_and_no_envelope(porth, table, queue):
    """The property, stated as an absence and checked as one.

    Re-verifying a token minted for a crossing that already finished would be
    verifying the wrong thing, and holding one open long enough to still verify
    would mean moving H2's 300-second ceiling for no gain.
    """
    call("hash_async", document={"amount": 1}, callback=CALLBACK)

    body = json.dumps(_sent(queue))
    for forbidden in ("porth_context", "token", "signature", "envelope"):
        assert forbidden not in body, f"{forbidden!r} reached the queue"


def test_what_is_queued_is_a_context_the_worker_can_restore(porth, table, queue):
    from porth_common.context import PersistedContext

    call("hash_async", document={"amount": 1}, callback=CALLBACK)

    restored = PersistedContext.restore(_sent(queue)["context"])

    assert restored.tenant_id == "acme"
    assert restored.environment == "prod"
    assert restored.source_service == "porth"


def test_accepting_work_writes_nothing_to_the_table(porth, table, queue):
    """`echo` stays the only writer, so the residue sweep stays a one-prefix
    question and `tenant.deleted` remains provably clean."""
    call("hash_async", document=1, callback=CALLBACK)

    assert not table.put_item.called
    assert not table.update_item.called


def test_an_unprovisioned_tenant_is_refused_at_the_door(porth, table, queue):
    """Cheaper and kinder than queueing successfully and dying out of sight —
    the caller is still on the line to be told."""
    porth.tenant_is_unknown()

    result = call("hash_async", document=1, callback=CALLBACK)

    assert result["error"]["code"] == "tenant_not_provisioned"
    assert not queue.send_message.called


def test_work_with_nowhere_to_report_is_refused(porth, table, queue):
    """ffug never holds an address to call back to, so the caller declares one.
    Asynchronous work whose result nobody learns is not worth accepting."""
    result = call("hash_async", document=1)

    assert result["error"]["code"] == "missing_callback"
    assert not queue.send_message.called


def test_the_synchronous_hash_is_untouched(porth, table, queue):
    """The async op is an addition. `hash` still answers in line."""
    result = call("hash", **{"amount": 1})

    assert result["prime"] == ACME_PRIME
    assert not queue.send_message.called


# --- the drainer -------------------------------------------------------------


def _record(message_id, tenant="acme"):
    return {
        "messageId": message_id,
        "body": json.dumps(
            {
                "context": json.dumps(
                    {
                        "environment": "prod",
                        "tenant_id": tenant,
                        "source_service": "porth",
                        "trace_id": f"trace-{tenant}",
                        "verified_at": 1,
                    }
                ),
                "payload": {"amount": 1},
                "callback": CALLBACK,
            }
        ),
    }


class _Scoped:
    def __init__(self, item, tenant, table):
        self.item = item
        self.index = 0
        self.director = MagicMock(
            environment="prod", tenant_id=tenant, async_trace_id=f"trace-{tenant}",
            # Who asked. Resumed from the PersistedContext in the real worker,
            # and the value the completion is addressed to (PORTH-623).
            source_service="alpha",
        )
        self.director.table = table


def test_the_worker_asks_for_one_director_per_record(monkeypatch):
    """Not an implementation detail — it is the isolation property.

    A batch carries several tenants and each record's Director must be narrowed
    to its own partition. What would break it while still working is hoisting
    one Director out of the loop, which reads as an optimisation.
    """
    seen = {}

    class _Batch:
        def __init__(self, items, **kwargs):
            seen.update(kwargs)
            seen["items"] = items
            self.refusals = ()
            self.refused_count = 0

        def __iter__(self):
            return iter(())

    monkeypatch.setattr(w, "PerRecordDirectors", _Batch)
    w.handler({"Records": [_record("m1")]})

    assert seen["director_cls"] is h.FfugDirector
    assert seen["context_of"](_record("m1")) is not None


def test_a_refused_record_becomes_a_batch_item_failure(monkeypatch):
    """Never a silent delete.

    Returning normally from an SQS handler deletes the WHOLE batch, refused
    records included — which is exactly the isolation failure this design exists
    to make visible.
    """
    refusal = MagicMock(index=0, reason_code="malformed_context", detail="bad",
                        tenant_id="", item={"messageId": "poison"})

    class _Batch:
        def __init__(self, items, **kwargs):
            self.refusals = (refusal,)
            self.refused_count = 1

        def __iter__(self):
            return iter(())

    monkeypatch.setattr(w, "PerRecordDirectors", _Batch)

    result = w.handler({"Records": [_record("poison")]})

    assert result["batchItemFailures"] == [{"itemIdentifier": "poison"}]


def test_one_failing_record_does_not_take_its_neighbours(monkeypatch, table):
    """The other half of ReportBatchItemFailures: a good record beside a bad one
    is completed and deleted, not redelivered forever alongside it."""
    good, bad = _record("good"), _record("bad", tenant="globex")
    table.get_item.return_value = {"Item": {"status": "active", "prime": ACME_PRIME}}

    class _Batch:
        def __init__(self, items, **kwargs):
            self.refusals = ()
            self.refused_count = 0

        def __iter__(self):
            return iter([_Scoped(good, "acme", table), _Scoped(bad, "globex", table)])

    monkeypatch.setattr(w, "PerRecordDirectors", _Batch)

    calls = []

    def send(director, declaration, payload):
        if director.tenant_id == "globex":
            raise RuntimeError("callee unreachable")
        calls.append((director.source_service, declaration.operation, payload))

    monkeypatch.setattr(w, "send_callback", send)

    result = w.handler({"Records": [good, bad]})

    assert result["batchItemFailures"] == [{"itemIdentifier": "bad"}]
    # Answered its own requester, taken from the Director rather than the body.
    assert calls and calls[0][:2] == ("alpha", "fingerprint-complete")


def test_the_completion_is_addressed_to_whoever_asked(monkeypatch, table):
    """The message says what to call AND where; ffug decides neither.

    This test used to assert the opposite — that the target came from the
    message — and the premise inverted (PORTH-623, Richard 2026-08-27). Naming
    the destination meant resolving THAT service's address, so ffug could serve
    exactly one requester; the second's answers would have gone to the first's
    ingress.

    Now the worker passes only the operation, and `send_callback` addresses the
    answer to the `source_service` it resumed with. ffug still holds no address
    and still cannot be pointed at one — and it can now answer any number of
    requesters, each at its own ingress.
    """
    table.get_item.return_value = {"Item": {"status": "active", "prime": ACME_PRIME}}
    item = _record("m1")

    class _Batch:
        def __init__(self, items, **kwargs):
            self.refusals = ()
            self.refused_count = 0

        def __iter__(self):
            return iter([_Scoped(item, "acme", table)])

    monkeypatch.setattr(w, "PerRecordDirectors", _Batch)
    seen = {}
    monkeypatch.setattr(
        w, "send_callback",
        lambda d, decl, payload: seen.update(
            operation=decl.operation, endpoint=decl.endpoint,
            answering=d.source_service, payload=payload,
        ),
    )

    w.handler({"Records": [item]})

    assert seen["operation"] == "fingerprint-complete"
    # The ADDRESS is relayed from the request body, untouched.
    assert seen["endpoint"] == {"mode": "invoke", "target": "alpha-callback"}
    # The AUDIENCE comes from the Director resumed from the persisted record,
    # never from the body. Keeping these two apart is what makes an unchecked
    # address safe.
    assert seen["answering"] == "alpha"
    assert seen["payload"]["prime"] == ACME_PRIME
    assert len(seen["payload"]["digest"]) == 64


def test_a_tenant_suspended_since_acceptance_is_refused_not_retried(monkeypatch, table):
    """A real outcome, not a transient fault. Redelivering would produce the
    same answer every time until the queue gave up."""
    table.get_item.return_value = {"Item": {"status": "suspended"}}
    item = _record("m1")

    class _Batch:
        def __init__(self, items, **kwargs):
            self.refusals = ()
            self.refused_count = 0

        def __iter__(self):
            return iter([_Scoped(item, "acme", table)])

    monkeypatch.setattr(w, "PerRecordDirectors", _Batch)
    monkeypatch.setattr(w, "send_callback", lambda *a, **k: pytest.fail("called back"))

    assert w.handler({"Records": [item]})["batchItemFailures"] == []
