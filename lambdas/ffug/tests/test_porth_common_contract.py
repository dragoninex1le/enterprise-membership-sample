"""The porth-common the suite is actually running against.

Written after a full green suite locally and 40 failures in CI on the same
commit. The cause was not the code: `porth_common` resolved to a source
checkout sitting on an old branch, so every local run had been testing against
0.0.10 while `lambdas/requirements.txt` asked for 0.0.11. A suite that passes
against the wrong library is worse than a red one — it reports confidence it
does not have.

These assert CAPABILITIES rather than a version string. A version is metadata
and can be absent, stale, or right while the code on the path is not; a
signature is the thing the code depends on. Each one names the contract EMS
actually consumes, so a mismatch says which promise is missing rather than
"expected 0.0.11".
"""

import inspect

import pytest


def test_get_context_takes_the_ingress_direction():
    """PORTH-623's compensating control.

    Verification went local, so IAM no longer enforces the request/response wall
    at receivers — the library does, and it can only do that if the ingress says
    which direction it accepts. Without this parameter the wall does not exist,
    and a response-direction kid would be accepted at a request door.
    """
    from porth_common.director import get_context

    assert "direction" in inspect.signature(get_context).parameters, (
        "porth-common on this path predates PORTH-623. lambdas/requirements.txt "
        "asks for >=0.0.11; check what is actually importable — a source "
        "checkout on the path shadows the installed package."
    )


def test_the_director_lets_an_ingress_declare_what_it_accepts():
    """`expects` defaults to REQUEST, which is why ffug's door needs no change.

    A callback ingress must pass Direction.RESPONSE. Asserted here because the
    default is what makes the migration invisible for existing services — and an
    invisible default is one nobody checks.
    """
    from porth_common.director import Director

    assert "expects" in inspect.signature(Director.__init__).parameters


def test_signing_keys_are_one_document_per_service():
    """PORTH-625's contract change.

    The template grants `signing-keys/*` as a prefix and the deploy registers
    per service. Against a porth-common that still expects one shared registry,
    both are wrong in ways that only show up at the first internal call.
    """
    from porth_common.internal_plane import signing_trust

    assert hasattr(signing_trust, "SigningKeyDocument"), (
        "this porth-common still has the pre-0.0.11 shared-registry shape"
    )


def test_verification_is_local_so_nothing_calls_kms_to_verify():
    """The reason ffug's role holds no kms:Verify.

    If this library still verified through KMS, the template would be granting
    nothing for a call it still makes — and the failure would arrive as
    `bad_signature`, which reads as forgery rather than as a missing grant.
    """
    from porth_common.context import envelope

    source = inspect.getsource(envelope)
    assert "_kms().verify(" not in source, (
        "this porth-common verifies through KMS; the template removed "
        "kms:Verify on the strength of local verification (PORTH-623)"
    )


# --- the wire shape, asserted across both sides (PORTH-622) -------------------
#
# This file exists for assumptions about porth_common that a mock would hide.
# The one below is the same species and cost a live deploy: ffug's ops read
# fields off the invocation event, the sample app sends them through
# ServiceClient, and NOTHING checked that the two agreed. ffug's tests built the
# event by hand in the shape ffug reads; the app's tests asserted what
# ServiceClient was called with. Both passed. Neither crossed the gap.


def _wire_event(payload):
    """Exactly what `ServiceClient._body` produces, plus what the transport adds.

    Built from the library's own function rather than restated, so a change to
    the envelope's shape fails here rather than being mirrored into a copy that
    quietly agrees with a version of porth_common nobody runs.
    """
    import os
    from unittest.mock import MagicMock, patch

    from porth_common.internal_plane.client import ServiceClient

    # ServiceClient refuses to exist without a registered identity, which is
    # correct and is checked in its constructor rather than at call time.
    with patch.dict(os.environ, {"PORTH_SERVICE_ID": "sample-app"}):
        body = ServiceClient(MagicMock())._body("hash_async", payload, None)
    return {**body, "porth_context": "<token>"}


def test_the_field_the_app_sends_is_the_field_ffug_reads():
    """The gap, closed by making both sides meet in one assertion.

    Not "ffug reads `document`" and separately "the app sends `document`" — that
    is two facts that can drift apart. This builds the caller's arguments, puts
    them on the wire the way the client does, and asserts the receiver finds
    them there.
    """
    from ffug import handler as h
    from sample_app.ffug_client import FINGERPRINT_CALLBACK

    document = {"record_type": "invoice", "record_id": "i-1"}
    # The caller's arguments, spelled exactly as ffug_client.fingerprint_async
    # spells them. If that call site changes, this line has to change with it —
    # which is the coupling being made visible rather than removed.
    event = _wire_event({"document": document, "callback": FINGERPRINT_CALLBACK})

    args = event.get("payload") or {}

    assert args.get("document") == document, (
        "the document is not where ffug looks for it; ffug reads args['document']"
    )
    assert args.get("callback") == FINGERPRINT_CALLBACK
    assert "callback" not in event, (
        "a top-level `callback` would mean ffug's original reading was right and "
        "this test is asserting the wrong shape"
    )


def test_no_op_reads_a_field_the_wire_never_carries():
    """The general rule, so a fifth op cannot reintroduce the defect.

    `ServiceClient` puts three keys on the wire — operation, payload (or
    payload_ref), porth_context. An op that reads anything else off the raw event
    reads a level nothing populates: loudly if the field is required, silently if
    it has a default, which is how `isolation_probe` ran with an empty
    probe_tenant from PORTH-598 until PORTH-622.
    """
    import inspect
    import re

    from ffug import handler as h

    source = inspect.getsource(h)
    # Only inside op bodies: the dispatcher reads `operation` off the event and
    # must keep doing so.
    ops = re.findall(r"\ndef (_op_\w+)\(.*?(?=\ndef |\Z)", source, re.S)
    bodies = re.findall(r"\ndef _op_\w+\(.*?(?=\ndef |\Z)", source, re.S)

    offenders = [
        (name, field)
        for name, body in zip(ops, bodies)
        for field in re.findall(r'event\.get\("(\w+)"\)', body)
    ]

    assert not offenders, (
        f"ops reading the raw event: {offenders}. An op receives its ARGUMENTS "
        f"— the dispatcher unwraps `payload` once, in one place, so there is no "
        f"per-op choice to get wrong."
    )


def test_every_director_declares_who_it_is():
    """Identity is declared, not inherited from the process (PORTH-623).

    An environment variable is one value for a whole process, so it cannot
    express an app that speaks as more than one service — and while it was the
    only source, a deployable could not present differently per ingress. That
    pressure is what makes a consumer invent extra service ids for what is
    really one service.

    Declaring it here also removes a drift: the value the code uses and the
    value the template sets were two statements of one fact, and
    `verify_callback` recomputes the correlation hash from this service's own
    registered identity — so a disagreement makes every authentic completion
    look like a mismatch.
    """
    from ffug.handler import FfugDirector
    from sample_app.director import SampleAppDirector
    from sample_app_callback.handler import CallbackDirector

    declared = {
        FfugDirector: "ffug",
        SampleAppDirector: "sample-app",
        CallbackDirector: "sample-app",
    }
    for cls, expected in declared.items():
        assert cls.SERVICE_ID == expected, (
            f"{cls.__name__} declares {cls.SERVICE_ID!r}, expected {expected!r}"
        )


def test_the_stubs_do_not_pin_the_libraries_signature():
    """A guard about the tests themselves, earned twice over.

    `get_context` gained `direction` in 0.0.11 and `service_id` in 0.0.12. Both
    times, stubs written as `lambda event, direction=None` broke everywhere at
    once — 40 CI failures the first time — for a reason that had nothing to do
    with what any of those tests were about.

    A stub standing in for verification should accept whatever verification is
    handed. Pinning its arity makes every upstream addition a bulk edit.
    """
    import ast
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2]

    # Parsed, not pattern-matched. Two regex attempts got this wrong in
    # different directions — one anchored to the start of the FILE and could
    # never fire, the other spanned the whole file and flagged an unrelated
    # lambda. The syntax tree says exactly which lambda is being handed to
    # get_context.
    offenders = []
    for f in root.rglob("test_*.py"):
        text = f.read_text()
        if "get_context" not in text:
            continue

        def pinned(args) -> bool:
            return not (args.vararg or args.kwarg)

        for node in ast.walk(ast.parse(text)):
            if not (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "setattr"):
                continue
            if not any(
                isinstance(a, ast.Constant) and "get_context" in str(a.value)
                for a in node.args
            ):
                continue
            for a in node.args:
                if isinstance(a, ast.Lambda) and pinned(a.args):
                    offenders.append(f"{f.name}: the get_context lambda")
                elif isinstance(a, ast.Name):
                    # A named function passed by reference — find its def.
                    for d in ast.walk(ast.parse(text)):
                        if (
                            isinstance(d, ast.FunctionDef)
                            and d.name == a.id
                            and pinned(d.args)
                        ):
                            offenders.append(f"{f.name}: def {d.name}(...)")

    assert not offenders, (
        "get_context stubs with a fixed signature: " + "; ".join(offenders)
    )
