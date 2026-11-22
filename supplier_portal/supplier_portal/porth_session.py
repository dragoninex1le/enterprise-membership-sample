"""Asking Porth for a supplier session — Porth's delegated mint, per its contract.

Contract: Porth ``docs/delegated-mint.md``. In short:

* The call goes to service ``porth-delegated-mint``, operation ``mint``, through
  porth-common's ``ServiceClient`` with a Director restored from a
  ``PersistedContext``. The tenant comes from that record — there is no tenant field.
* The body is exactly: ``connector_type``, ``external_id``, ``verification``
  (``reference``, ``method``, ``verified_at``), ``host_credential_expires_at``, and
  optionally ``store_external_id``, ``role_claim`` and ``permission_claims`` (Porth
  ≥ 0.4.26). Unknown fields are refused. EMS sends each claim the assertion carried,
  as signed; the buyer's mapping for the network reads one of them.
* Porth answers ``{"ok": true, "token", "session_id", "expires_at"}`` or
  ``{"ok": false, "error": {"code", "message"}}``. A refusal is an answer, not a fault.
* The token is returned once. It is never logged here; ``session_id`` is.

Warming (Porth ≥ 0.4.26, "Warming the mint before a login"): with ``PORTH_MINT_WARM=1``
the handler starts a signed ``warm`` call for the host's tenant before it reads the
network key and checks the assertion, and the mint waits for it (at most
``WARM_WAIT_SECONDS``) so it lands on the container the warm call warmed. A warm call
never fails a login, is never retried and is never cancelled. Off by default: an older
Porth reads ``warm`` as a malformed mint and its refusal alarm counts it.

What this function's role must hold (template.yml ``SupplierPortalRole``): ``kms:Sign``
on Porth's mint request key (by alias), invoke on ``porth-{branch}-delegated-mint``,
read on ``/porth/{branch}/services/*`` — and Porth's install Terraform must list the
role in ``delegated_mint_caller_role_arns``, which is the actual control.
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any

from supplier_portal import trace
from supplier_portal.assertion import SupplierContact

log = logging.getLogger("supplier_portal.porth_session")

SERVICE = "porth-delegated-mint"

#: Longer than a cold warm call (a few seconds); past it the mint goes anyway.
WARM_WAIT_SECONDS = 6.0
_warm_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="porth-warm")

#: How each of Porth's refusal codes is answered to the supplier's client.
ANSWER_STATUS = {
    "host_credential_expired": 401,
    "connector_not_enabled": 403,
    "unmapped_role_claim": 403,
    "no_role_for_permissions": 403,
    "role_exceeds_ceiling": 403,
    "tenant_not_active": 403,
    "platform_tenant_refused": 403,
    "duplicate_reference": 409,
    "rate_limited": 429,
}


@dataclass(frozen=True)
class Outcome:
    """What Porth said. ``token`` is set only on success and must not be logged."""

    granted: bool
    status: int
    code: str = ""
    token: str = ""
    session_id: str = ""
    expires_at: int = 0
    api_base_url: str = ""


def request_body(contact: SupplierContact) -> dict[str, Any]:
    return {
        "connector_type": contact.connector,
        # Porth names the delegated principal {connector}:{external_id}; a contact id
        # is unique only within its supplier, so the supplier is part of it.
        "external_id": f"{contact.supplier}.{contact.contact}",
        "verification": {
            "reference": f"{contact.buyer}/{contact.assertion_id}",
            "method": "supplierlink-es256-assertion",
            "verified_at": contact.checked_at,
        },
        "host_credential_expires_at": contact.valid_until,
        "store_external_id": contact.supplier,
        **({"role_claim": contact.role} if contact.role else {}),
        **({"permission_claims": list(contact.permissions)} if contact.permissions else {}),
    }


def warming_on() -> bool:
    return os.environ.get("PORTH_MINT_WARM", "0") == "1"


def start_warm(record: Any, connector_type: str, *, call=None) -> Future | None:
    """Start the warm call in the background; None when warming is off.

    ``record`` is the host tenant's PersistedContext — the same tenant the mint will
    name (the handler refuses a link to any other tenant). ``call`` is the transport
    (tests replace it)."""
    if not warming_on():
        return None
    send = call or _warm_over_internal_plane
    trace.event("warm.start", service=SERVICE, tenant=record.tenant_id, connector_type=connector_type)
    return _warm_pool.submit(_warm, send, record, connector_type)


def _warm(send, record: Any, connector_type: str) -> None:
    started = time.monotonic()
    try:
        answer = send(record, {"connector_type": connector_type})
        ok = isinstance(answer, dict) and answer.get("ok") is True
        trace.event("warm.answered", ok=ok, ms=round((time.monotonic() - started) * 1000, 1),
                    warmed=(answer or {}).get("warmed") if isinstance(answer, dict) else None,
                    error=(answer or {}).get("error") if isinstance(answer, dict) and not ok else None)
    except Exception as exc:  # noqa: BLE001 — a warm call must never fail a login
        trace.event("warm.failed", reason=f"{type(exc).__name__}: {str(exc)[:200]}",
                    ms=round((time.monotonic() - started) * 1000, 1))


def request_session(record: Any, contact: SupplierContact, *, call=None,
                    warming: Future | None = None) -> Outcome:
    """Ask Porth. ``call`` is the transport (tests replace it); by default porth-common's.
    ``warming`` is the warm call started for this login: the mint waits for it first."""
    if warming is not None:
        started = time.monotonic()
        done, _ = wait([warming], timeout=WARM_WAIT_SECONDS)  # never raises, never cancels
        trace.event("warm.waited", done=bool(done), ms=round((time.monotonic() - started) * 1000, 1))
    send = call or _over_internal_plane
    body = request_body(contact)
    # The request carries no secret: ids, the reference, the host's words, expiry.
    trace.event("mint.request", service=SERVICE, tenant=record.tenant_id, **{
        "connector_type": body["connector_type"], "external_id": body["external_id"],
        "reference": body["verification"]["reference"], "role_claim": body.get("role_claim"),
        "permission_claims": body.get("permission_claims"),
        "store_external_id": body["store_external_id"],
        "host_credential_expires_at": body["host_credential_expires_at"]})
    started = time.monotonic()
    try:
        answer = send(record, body)
    except _Unreachable as exc:
        log.error("porth_session.unreachable reason=%s", exc)
        return Outcome(granted=False, status=503, code="porth_unavailable")
    finally:
        trace.event("mint.answered", ms=round((time.monotonic() - started) * 1000, 1))
    # The answer's shape, never its token.
    trace.event("mint.answer", ok=isinstance(answer, dict) and answer.get("ok"),
                keys=sorted(answer) if isinstance(answer, dict) else type(answer).__name__,
                error=((answer or {}).get("error") if isinstance(answer, dict) else None))

    if isinstance(answer, dict) and answer.get("ok") is True:
        token, session_id, expires_at = answer.get("token"), answer.get("session_id"), answer.get("expires_at")
        if token and session_id and expires_at:
            log.info("porth_session.granted tenant=%s supplier=%s session_id=%s expires_at=%s",
                     record.tenant_id, contact.supplier, session_id, expires_at)
            return Outcome(granted=True, status=200, token=str(token), session_id=str(session_id),
                           expires_at=int(expires_at), api_base_url=str(answer.get("api_base_url") or ""))
        log.error("porth_session.incomplete_answer tenant=%s", record.tenant_id)
        return Outcome(granted=False, status=503, code="porth_unavailable")

    code = str(((answer or {}).get("error") or {}).get("code") or "internal_error") if isinstance(answer, dict) else "internal_error"
    log.warning("porth_session.refused tenant=%s supplier=%s code=%s", record.tenant_id, contact.supplier, code)
    return Outcome(granted=False, status=ANSWER_STATUS.get(code.split(":")[0], 502), code=code)


class _Unreachable(Exception):
    pass


def _over_internal_plane(record: Any, body: dict[str, Any]) -> Any:
    try:
        return _call(record, "mint", body)
    except Exception as exc:  # any transport, envelope or registry failure: Porth did not answer
        raise _Unreachable(f"{type(exc).__name__}: {str(exc)[:200]}") from exc


def _warm_over_internal_plane(record: Any, body: dict[str, Any]) -> Any:
    return _call(record, "warm", body)


def _call(record: Any, operation: str, body: dict[str, Any]) -> Any:
    # porth-common >= 0.0.28 shares one Lambda client per process, so the mint goes out
    # on the connection the warm call opened; the same tenant reuses its envelope token.
    from porth_common.director import Director
    from porth_common.internal_plane.client import ServiceClient

    return ServiceClient(Director.from_persisted_context(record)).call(SERVICE, operation, body)
