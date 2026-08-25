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

from porth_common.internal_plane.client import ServiceClient

log = logging.getLogger(__name__)

FFUG_SERVICE_ID = "ffug"


class FfugUnavailable(Exception):
    """ffug could not be reached, or refused."""


class FingerprintUnavailable(FfugUnavailable):
    """The specific case above, for the approval path. Never fatal to an approval."""


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
    except Exception as exc:  # noqa: BLE001 — see below; the breadth is the fix
        # PORTH-603. This caught ServiceCallError only, and that was too narrow
        # to hold the promise the caller makes.
        #
        # ServiceCallError covers the ways a CALL can fail — unregistered,
        # suspended, unreachable, oversized, callee raising. It does not cover
        # the ways the plane can fail to be RESOLVED: reading the registry and
        # the endpoint map happens first, and a ConfigurationUnavailableError
        # is not a ServiceCallError. So a missing ssm:GetParameter escaped this
        # handler entirely and approve() returned 500 — with the approval
        # already committed, because the decision is written before the
        # fingerprint is sought.
        #
        # That is the exact failure this design says must not happen: a fixture
        # service on the internal plane must not fail a business decision. The
        # handler now matches the promise rather than one family of it.
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


#: Where ffug should deliver a completion. A service and an operation — never an
#: address. The endpoint is resolved from the D7.4 map at send time, on ffug's
#: side, so this app cannot hand a worker somewhere to post to and a compromised
#: worker cannot be told to post somewhere else.
FINGERPRINT_CALLBACK = {"service_id": "sample-app", "operation": "fingerprint-complete"}


def fingerprint_async(director, document: dict[str, Any], *, trace_id: str) -> str:
    """Ask ffug to fingerprint *document* later, and return the accepted trace id.

    The crossing itself is as synchronous as any other — a RequestResponse
    invoke that returns as soon as ffug has taken the work. What is asynchronous
    is the *work*, and the answer comes back as a fresh crossing in the opposite
    direction rather than as this call's return value.

    ``trace_id`` is passed rather than derived, and it is the same value the
    caller has already hashed into the record. It has to be: it rides in the
    signed envelope, ffug persists it with the context, and it comes back in the
    callback's claims as the only thing tying the answer to the question. Letting
    this function mint one would mean the initiator hashed an identity the call
    never carried, and every callback would look like a correlation mismatch.

    ``idempotent=True`` is unchanged in meaning and is a narrower claim than it
    looks: retrying THIS call is safe because it re-queues the same work under
    the same trace, and a duplicate completion is the benign outcome the
    correlation check tolerates by design.
    """
    try:
        body = ServiceClient(director).call(
            FFUG_SERVICE_ID,
            "hash_async",
            # `document`, not `payload`. What is passed here BECOMES the
            # `payload` field on the wire, so a key called `payload` inside it
            # reads as payload.payload at the far end — which is how the first
            # live attempt refused every call with missing_callback.
            {"document": document, "callback": FINGERPRINT_CALLBACK},
            idempotent=True,
            trace_id=trace_id,
        )
    except Exception as exc:  # noqa: BLE001 — same breadth as fingerprint(), same reason
        raise FingerprintUnavailable(str(exc)) from exc

    if not isinstance(body, dict) or not body.get("ok"):
        error = (body or {}).get("error", {}) if isinstance(body, dict) else {}
        raise FingerprintUnavailable(
            f"{error.get('code', 'refused')}: {error.get('message', '')}"
        )

    accepted = str(body.get("trace_id") or "")
    if accepted != trace_id:
        # Not a formality. The stored correlation hash is anchored to the trace
        # WE sent; if ffug is working under a different one, every callback will
        # arrive authentic and refuse to correlate, and the fault will look like
        # a mismatch at the receiving end rather than a disagreement here.
        raise FingerprintUnavailable(
            f"ffug accepted the work under trace {accepted!r}, not {trace_id!r}"
        )

    log.info(
        "sample_app.fingerprint_queued tenant_id=%s trace_id=%s",
        director.tenant_id, trace_id,
    )
    return accepted


def isolation_probe(director, probe_tenant: str = "") -> dict[str, Any]:
    """Ask ffug what its OWN narrowed session can reach in its OWN table.

    Never raises. This feeds a diagnostics panel whose job is to explain why
    things are broken, so a failure has to arrive as something renderable — an
    endpoint that 500s in the situation it exists to describe is no use.

    Note what is not sent: the tenant ffug SERVES. There is no field for it —
    ffug takes it from the signed envelope this call carries, which is the
    property being demonstrated.

    ``probe_tenant`` is a different thing and is safe to let the caller choose:
    it scopes nothing, and only names a partition the probe asserts must be
    REFUSED. Its point is to aim a refusal at a tenant that really exists, so
    the denial cannot be read as "there was nothing there anyway".
    """
    try:
        body = ServiceClient(director).call(
            FFUG_SERVICE_ID,
            "isolation_probe",
            {"probe_tenant": probe_tenant} if probe_tenant else {},
            idempotent=True,
            trace_id=getattr(director, "trace_id", None) or None,
        )
    except Exception as exc:  # noqa: BLE001 — a diagnostic must not die
        # Same widening as above, and it matters more here. This endpoint's one
        # job is to explain why things are broken; catching only ServiceCallError
        # made it 500 on a configuration fault — the page that should have
        # rendered "ffug unreachable: could not read 'services' from
        # /porth/dev/services" instead crashed and said nothing at all.
        #
        # Same shape as PORTH-612: a diagnostic that fails in the situation it
        # exists to diagnose sends the reader looking somewhere else.
        log.warning("sample_app.probe could not reach ffug: %s", exc)
        return {"ok": False, "error": str(exc)}

    if not isinstance(body, dict) or not body.get("ok"):
        error = (body or {}).get("error", {}) if isinstance(body, dict) else {}
        return {
            "ok": False,
            "error": f"{error.get('code', 'refused')}: {error.get('message', '')}",
        }
    return body
