"""Ask ffug to fingerprint a document for this request's tenant (PORTH-599).

Thin on purpose. Everything about *how* a service is reached belongs to
:class:`porth_common.internal_plane.client.ServiceClient`, and this module's
only job is to name the service, the operation, and what is being hashed.

An earlier version of this file built its own Lambda client and invoked ffug
directly. It worked, and it quietly gave up four things the sanctioned client
holds — the reason `scripts/check_service_calls.py` fails Porth's build on
exactly that shape:

* **the endpoint map.** A hand-rolled invoke hard-codes a transport and an
  address at the call site, so it cannot follow ``/porth/{branch}/service-endpoints``
  and only ever works in-install. The same ``call()`` works from a laptop
  against the deployed service, because that difference is configuration.
* **the retry rule.** botocore fixes retry behaviour at client construction, so
  the default client silently retries. ``idempotent=`` is the caller's explicit
  assertion, and the client keeps two clients so a non-idempotent operation is
  genuinely attempted once rather than merely not looped over.
* **the payload ceiling.** Refused at a stated limit instead of succeeding at
  200 KB and failing unpredictably nearer the platform's.
* **caller-side status.** The D3 registry is consulted BEFORE a transport is
  chosen, so a suspended service refuses at both ends rather than only at the
  receiver.

What travels is unchanged and is the point. The tenant is not a parameter here
and there is no way to pass one: it rides in a KMS-signed envelope the client
builds from the Director, which got it from Porth's own resolution of the
caller. The invoke itself is plain IAM. *Context propagates, credentials never
do.*
"""

from __future__ import annotations

import logging
from typing import Any

from porth_common.internal_plane.client import ServiceClient, ServiceCallError

log = logging.getLogger(__name__)

FFUG_SERVICE_ID = "ffug"


class FingerprintUnavailable(Exception):
    """ffug could not be reached, or refused. Never fatal to an approval."""


def fingerprint(director, document: dict[str, Any]) -> dict[str, str]:
    """Return ``{"prime": …, "digest": …}`` for *document* under this tenant.

    ``idempotent=True`` is an honest assertion rather than a convenience:
    hashing has no side effect, the same document under the same tenant yields
    the same digest, and a repeat costs nothing. Defaulting to False here would
    disable retries on an operation that is safe to repeat.

    Raises :class:`FingerprintUnavailable` with ffug's own reason. The caller
    decides what that means; approving a real invoice should not fail because a
    fixture service is unreachable, but the failure must be visible rather than
    swallowed into a blank field.
    """
    try:
        body = ServiceClient(director).call(
            FFUG_SERVICE_ID,
            "hash",
            document,
            idempotent=True,
            trace_id=getattr(director, "trace_id", None) or None,
        )
    except ServiceCallError as exc:
        # One family for every way the plane can fail: unregistered, suspended,
        # unreachable, oversized, or the callee raising. Rendered to the
        # approver as-is, because "approved but not fingerprinted — <this>" is
        # more use than a generic apology.
        raise FingerprintUnavailable(str(exc)) from exc

    if not isinstance(body, dict) or not body.get("ok"):
        error = (body or {}).get("error", {}) if isinstance(body, dict) else {}
        raise FingerprintUnavailable(
            f"{error.get('code', 'refused')}: {error.get('message', '')}"
        )

    # Identifiers only. The prime is not a secret (see ffug's salt.py) but the
    # document is this tenant's data and does not belong in a log line.
    log.info(
        "sample_app.fingerprint tenant_id=%s digest=%s",
        director.tenant_id, str(body["digest"])[:12],
    )
    return {"prime": str(body["prime"]), "digest": str(body["digest"])}
