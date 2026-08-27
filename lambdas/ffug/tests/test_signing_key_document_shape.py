"""The trust documents Terraform writes, checked against the schema that loads them.

`infra/terraform/ems-install-once` writes `/porth/{branch}/signing-keys/{service}`
directly, rather than shelling out to `porth-install signing-key register`. That
is the right owner — each document has exactly one writer under PORTH-625, so
there is nothing to merge with — but it gives up the one thing the command did
that HCL cannot: validating the result through the same code the runtime loads
it with.

This is that check, moved earlier. It runs in CI rather than at apply time, so a
document shape porth-common would refuse fails on the pull request instead of at
the first internal call of the day.
"""

import base64
import json
import re
from pathlib import Path

import pytest

MAIN_TF = (
    Path(__file__).resolve().parents[3]
    / "infra" / "terraform" / "ems-install-once" / "main.tf"
)


@pytest.fixture(scope="module")
def trust_document_block():
    """The `trust_documents` local, as text."""
    source = MAIN_TF.read_text()
    start = source.index("trust_documents = {")
    end = source.index('resource "aws_ssm_parameter" "signing_keys"')
    return source[start:end]


def test_the_terraform_emits_every_field_the_schema_requires(trust_document_block):
    """Drift detector, and the direction that matters.

    If porth-common gains a required field this fails here and names it, rather
    than the apply succeeding and every crossing being refused because a
    document three commits old no longer validates.
    """
    from porth_common.internal_plane.signing_trust import SigningKeyDocument, SigningKeyEntry

    required = {k for k, v in SigningKeyEntry.model_fields.items() if v.is_required()}
    required |= {k for k, v in SigningKeyDocument.model_fields.items() if v.is_required()}

    for field in sorted(required):
        assert re.search(rf"\b{field}\b\s*=", trust_document_block), (
            f"the trust document in {MAIN_TF.name} does not set {field!r}, which "
            f"porth-common requires. Terraform writes these documents directly, "
            f"so a schema change has to be reflected there."
        )


def test_a_document_of_that_shape_actually_loads():
    """The shape, run through the loader the runtime uses.

    Kept alongside the field check because the two fail differently: that one
    catches a field going missing, this one catches the document being
    structurally wrong in a way a field list cannot express — a nested key, a
    stringified integer, an entry list that is not a list.
    """
    from porth_common.internal_plane.signing_trust import validate_document

    document = {
        "contract_version": 1,
        "service_id": "ffug",
        "keys": [
            {
                "alias": "alias/porth-context-ffug-response-dev",
                "direction": "response",
                "public_key": base64.b64encode(b"not a real key, but valid base64").decode(),
                "description": "EMS ffug response",
            }
        ],
    }

    parsed = validate_document(json.dumps(document), expected_service_id="ffug")

    assert parsed.service_id == "ffug"
    # Resolved by DIRECTION, not by a key identifier. The document no longer
    # stores a kid: the kid names which key made a signature and rides in the
    # envelope, so what a reader needs here is the alias to sign with and the
    # public key to check against (PORTH-623).
    direction = parsed.keys[0].direction
    assert parsed.signing_alias(direction) == document["keys"][0]["alias"]
    assert parsed.public_keys_for(direction), "no key to verify a signature against"


def test_the_app_is_not_a_service_of_its_own():
    """The inverse of the guard that used to live here (Richard, 2026-08-27).

    There was a hand-written `sample-app` document merged in beside the
    generated one, holding Porth's install key as "the app's request key". It
    existed because a token's signer is looked up by the service the token
    CLAIMS to be from, and the app claimed to be someone else.

    It no longer does. There is one service — ffug — and the app is its front
    half; `services/ffug` names both ingresses by direction and carries a key
    for each. So the document has no reader, and this asserts it stays gone:
    re-adding it would restore the second identity without restoring the reason
    for it, and a stale document that still validates is exactly the kind of
    thing that survives review.

    The old guard was right about its own world. Its failure message —
    "removing it looks like tidying" — is why this replaces it rather than
    being deleted: the next reader deserves to find the answer, not the gap.
    """
    source = MAIN_TF.read_text()

    assert '"sample-app" = {' not in source, (
        "a hand-written sample-app trust document is back. The app is not a "
        "service on the internal plane — it signs as ffug, with ffug's request "
        "key, and services/ffug describes the whole conversation."
    )
    assert "install_signing_key" not in source, (
        "Porth's install key is being read again. It was fetched only to give "
        "the app a document of its own; the app now signs with ffug's request "
        "key, which this module creates."
    )


def test_every_document_is_generated_from_the_key_pairs():
    """One rule produces every document — no `merge()` bolting on a second.

    The merge existed for exactly one argument: the hand-written sample-app
    document. With it gone, a document that is not derivable from a
    (service, direction) pair cannot be written at all, which is the property
    that keeps the keys and the documents from drifting.
    """
    source = MAIN_TF.read_text()

    assert "trust_documents = {" in source
    assert "trust_documents = merge(" not in source, (
        "a second source of trust documents is back. Anything merged in beside "
        "the generated map is a document with no key pair behind it."
    )


def test_ffug_holds_both_directions_because_it_is_on_both_legs():
    """The service is on both ends of its own conversation (Richard, 2026-08-25).

    A request goes in and a completion comes back, and both are ffug's — so its
    document carries a request key AND a response key.

    The response key alone was defensible only while the calling app was a
    SEPARATE service signing with its own key, which made ffug a pure callee
    that never originates. That is the shape being corrected. One direction is
    genuinely right for a pure callee or a fire-and-forget target; it is not
    right here.

    Asserted against the Terraform variable rather than the rendered document,
    because that is where a key is dropped: the document is generated from it,
    so a missing pair produces a document that validates perfectly and is
    missing a key.
    """
    import pathlib

    main = (pathlib.Path(__file__).resolve().parents[3]
            / "infra/terraform/ems-install-once/variables.tf").read_text()

    for direction in ("request", "response"):
        pair = '{ service_id = "ffug", direction = "%s" }' % direction
        assert pair in main, f"ffug has no {direction} key declared"


def test_the_registry_holds_no_callback_address():
    """The configuration PORTH-624 removed, asserted gone.

    `services/{id}` says where a service is CALLED, what it signs with, and
    whether it is active. It used to also carry a `directions.response` entry
    naming this app's callback ingress.

    That was a copy of a fact its owner already knew, in a document that could
    hold exactly one of them — so a second requester's answers would have been
    delivered to the first's ingress. A requester now supplies its own address
    when it asks, and ffug relays it untouched.

    Asserted here rather than left to the round trip because re-adding it would
    not fail anything: `resolve` prefers a direction override when one exists,
    so a stray entry would silently take precedence over the address the caller
    gave and send answers to whoever the operator wrote down.
    """
    source = MAIN_TF.read_text()
    # An assignment, not the word — the comment explaining the absence should
    # not trip a guard about the presence.
    assert not re.search(r"^\s*directions\s*=", source, re.M), (
        "a direction override is back in the trust document. A callback "
        "address in the registry takes precedence over the one the requester "
        "supplied, and can name only one requester."
    )
    assert not re.search(r'"[^"]*sample-app-callback[^"]*"', source), (
        "the callback function is named in a Terraform string again. Where this "
        "app receives answers is app configuration "
        "(SAMPLE_APP_CALLBACK_TARGET in template.yml), not something Porth's "
        "registry holds."
    )
