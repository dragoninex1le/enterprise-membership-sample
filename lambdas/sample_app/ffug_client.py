"""Ask ffug to fingerprint a document for this request's tenant (PORTH-599).

The one place this app crosses onto Porth's internal plane, and it is worth
being precise about what travels:

**The tenant does not.** It is not a parameter here and there is no way to pass
one. It rides inside a KMS-signed context envelope built by the Director, which
got it from Porth's own resolution of the caller — so ffug learns which tenant
this is from a signature it verifies, not from anything this app asserts. That
is ADR-Z11's rule stated as code: *context propagates, credentials never do.*

**Credentials do not either.** The invoke itself is plain IAM on this function's
execution role. ffug then narrows ITS own credentials to the tenant in the
verified envelope. Two services, two narrowings, one context — and at no point
does one service hand the other something it could act with.

What comes back is `SHA256(prime : document)`, where the prime was minted for
this tenant by ffug's bus consumer on `tenant.created` and can be read by
nothing else. Two tenants approving identical documents get different
fingerprints, and neither could produce the other's: ffug serving tenant A holds
a session that cannot read B's prime.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3

log = logging.getLogger(__name__)

FFUG_FUNCTION_ARN = os.environ.get("FFUG_FUNCTION_ARN", "")

#: This app's registered identity on the D3 service registry. ffug validates it
#: against `/porth/{branch}/services` and refuses an unregistered caller, so
#: this string is not decoration — a name nobody registered is a refused call.
SOURCE_SERVICE = "sample-app"
AUDIENCE = "ffug"

_lambda = None


def _client():
    """Module-level handle, built once per warm container.

    Deliberately NOT `director.client(...)`. The Director's connections are
    built from credentials narrowed to one tenant's DynamoDB partition; they
    grant no Lambda invoke and never should. Being allowed to call ffug is a
    property of this FUNCTION, not of the tenant whose request it is serving.
    """
    global _lambda
    if _lambda is None:
        _lambda = boto3.client("lambda")
    return _lambda


class FingerprintUnavailable(Exception):
    """ffug could not be reached, or refused. Never fatal to an approval."""


def fingerprint(director, document: dict[str, Any]) -> dict[str, str]:
    """Return ``{"prime": …, "digest": …}`` for *document* under this tenant.

    Raises :class:`FingerprintUnavailable` with ffug's own reason. The caller
    decides what that means; approving a real invoice should not fail because a
    fixture service is unreachable, but the failure must be visible rather than
    swallowed into a blank field.
    """
    if not FFUG_FUNCTION_ARN:
        raise FingerprintUnavailable("FFUG_FUNCTION_ARN is not set on this function")

    # The only sanctioned way to produce one. The tenant comes from THIS
    # Director, which is bound to a validated tenant, so no call site can pass a
    # tenant of its choosing — the property TS-MC.1 fails a build over.
    envelope = director.build_context_envelope(
        source_service=SOURCE_SERVICE,
        audience=AUDIENCE,
        trace_id=getattr(director, "trace_id", None) or None,
    )

    payload = {
        "porth_context": envelope.to_payload_field(),
        "op": "hash",
        "payload": document,
    }

    try:
        response = _client().invoke(
            FunctionName=FFUG_FUNCTION_ARN,
            Payload=json.dumps(payload).encode("utf-8"),
        )
    except Exception as exc:  # noqa: BLE001
        raise FingerprintUnavailable(f"could not invoke ffug: {exc}") from exc

    if response.get("FunctionError"):
        # An unhandled error inside ffug is an infrastructure fault — most
        # likely its STS narrowing — and is not something to render as a
        # business outcome.
        raise FingerprintUnavailable("ffug raised; see its log group")

    body = json.loads(response["Payload"].read())
    if not body.get("ok"):
        error = body.get("error", {})
        raise FingerprintUnavailable(
            f"{error.get('code', 'refused')}: {error.get('message', '')}"
        )

    # Identifiers only. The prime is not a secret (see ffug's salt.py) but the
    # document is this tenant's data and does not belong in a log line.
    log.info(
        "sample_app.fingerprint tenant_id=%s digest=%s",
        director.tenant_id, body["digest"][:12],
    )
    return {"prime": str(body["prime"]), "digest": body["digest"]}
