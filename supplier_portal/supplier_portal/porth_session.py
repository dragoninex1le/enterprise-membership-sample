"""Asking Porth for a supplier session — Porth's delegated mint, per its contract.

Contract: Porth ``docs/delegated-mint.md``. In short:

* The call goes to service ``porth-delegated-mint``, operation ``mint``, through
  porth-common's ``ServiceClient`` with a Director restored from a
  ``PersistedContext``. The tenant comes from that record — there is no tenant field.
* The body is exactly: ``connector_type``, ``external_id``, ``verification``
  (``reference``, ``method``, ``verified_at``), ``host_credential_expires_at``, and
  optionally ``store_external_id`` and ``role_claim``. Unknown fields are refused.
* Porth answers ``{"ok": true, "token", "session_id", "expires_at"}`` or
  ``{"ok": false, "error": {"code", "message"}}``. A refusal is an answer, not a fault.
* The token is returned once. It is never logged here; ``session_id`` is.

What this function's role must hold (template.yml ``SupplierPortalRole``): ``kms:Sign``
on Porth's mint request key (by alias), invoke on ``porth-{branch}-delegated-mint``,
read on ``/porth/{branch}/services/*`` — and Porth's install Terraform must list the
role in ``delegated_mint_caller_role_arns``, which is the actual control.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from supplier_portal.assertion import SupplierContact

log = logging.getLogger("supplier_portal.porth_session")

SERVICE = "porth-delegated-mint"

#: How each of Porth's refusal codes is answered to the supplier's client.
ANSWER_STATUS = {
    "host_credential_expired": 401,
    "connector_not_enabled": 403,
    "unmapped_role_claim": 403,
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
        "role_claim": contact.role,
    }


def request_session(record: Any, contact: SupplierContact, *, call=None) -> Outcome:
    """Ask Porth. ``call`` is the transport (tests replace it); by default porth-common's."""
    send = call or _over_internal_plane
    try:
        answer = send(record, request_body(contact))
    except _Unreachable as exc:
        log.error("porth_session.unreachable reason=%s", exc)
        return Outcome(granted=False, status=503, code="porth_unavailable")

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
    from porth_common.director import Director
    from porth_common.internal_plane.client import ServiceClient

    try:
        return ServiceClient(Director.from_persisted_context(record)).call(SERVICE, "mint", body)
    except Exception as exc:  # any transport, envelope or registry failure: Porth did not answer
        raise _Unreachable(f"{type(exc).__name__}: {str(exc)[:200]}") from exc
