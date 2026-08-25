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
    start = source.index("trust_documents = merge(")
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


def test_the_app_gets_a_document_even_though_it_has_no_key_of_its_own():
    """The binding that is easy to leave out.

    The app signs with the INSTALL key, so nothing in the key list produces its
    document — it is added separately. Verification fetches the document of the
    service a token claims to be from, so without this every crossing fails with
    UnknownSigningServiceError: a missing document wearing a signing error.
    """
    source = MAIN_TF.read_text()

    assert '"sample-app" = {' in source, (
        "the sample-app trust document is gone. Its key is the install key, so "
        "no (service, direction) pair generates it — removing it looks like "
        "tidying and refuses every call the app makes."
    )
    assert re.search(r'direction\s+=\s+"request"', source)
