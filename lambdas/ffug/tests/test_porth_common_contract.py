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
