"""ffug — the ADR-Z11 UAT compute target (PORTH-555 Phase A, PORTH-587 Phase B).

**Phase B landed here.** The module docstring used to say that
``resolve_tenant_context`` was "the single seam that changes"; this is that
change. Tenant and environment no longer ride the payload. They come from a
KMS-signed context envelope that :class:`porth_common.director.Director`
verifies before returning anything, and the data access underneath runs on an
STS session narrowed to that one tenant.

What that buys, stated precisely because the fixture exists to demonstrate it:

* **A caller cannot name its own tenant.** ``tenant_id`` is not a field ffug
  reads. It is a signed claim, and forging one requires ``kms:Sign`` on the
  install's context key — which ffug's own role deliberately does not hold
  (HoS condition H1; the denial is what UAT-4 witnesses).
* **Reaching another tenant's partition is refused by DynamoDB, not by ffug.**
  The narrowed session carries a ``dynamodb:LeadingKeys`` condition pinned to
  ``ENV#{env}#TENANT#{tenant}``. There is no branch in this file that could be
  wrong about it, and no ambient DynamoDB grant on the function role to fall
  back to — a narrowing failure is ``AccessDenied``, never silent wide access.
* **The tenant's salt was minted by something else entirely.** ``lifecycle.py``
  seeds it off the bus on ``tenant.created``. This path can read it and cannot
  create it: a caller arriving before the event is refused rather than served
  under an invented salt.

Operations: ``echo`` (store a payload under the caller's tenant, hand it back),
``get`` (read it back), ``hash`` (return ``SHA256(salt : payload)``). Named in
the ``operation`` field, which is what
:class:`porth_common.internal_plane.client.ServiceClient` sends. ``hash`` is the
addition, and it is the reason PORTH-587 amends the "no business logic" rule —
see README.md. It writes nothing, so ``echo`` remains the only writer and the
residue sweep stays a one-prefix question.

Public-repo note (PORTH-533): this repo's Actions logs are world-readable. Log
identifiers only — never a salt, never a payload body, never a token.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from porth_common.context.envelope import EnvelopeError
from porth_common.director import Director
from porth_common.internal_plane.config import (
    ServiceNotActiveError,
    ServicesConfigError,
    UnknownServiceError,
)
from porth_common.protocols.cloud_clients import DOCUMENT_STORE

from . import keys, salt

log = logging.getLogger(__name__)
log.setLevel(os.environ.get("FFUG_LOG_LEVEL", "INFO"))

TABLE_NAME = os.environ.get("FFUG_TABLE_NAME", "")


class FfugError(Exception):
    """Typed rejection. Carries a stable code so callers can assert on it."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_response(self) -> dict[str, Any]:
        return {"ok": False, "error": {"code": self.code, "message": self.message}}


class FfugDirector(Director):
    """The shared Director, plus ffug's one table.

    ``RESOURCES`` makes the narrowing eager: the STS exchange happens while the
    Director is being built, so a narrowing failure is raised at the boundary
    naming the capability, rather than several frames inside an op wearing
    whatever exception the first DynamoDB call happened to produce.
    """

    RESOURCES = ((DOCUMENT_STORE, "resource"),)

    @property
    def table(self):
        """ffug's table, reached through THIS request's narrowed credentials.

        The argument is a CAPABILITY, not an AWS service name. ``DOCUMENT_STORE``
        maps to DynamoDB on AWS and to Firestore or Cosmos DB elsewhere; passing
        the string ``"dynamodb"`` raises ``UnknownCapabilityError`` at runtime,
        which cost the sample app every one of its pages in PORTH-615. Imported
        rather than spelled, so the same mistake is an ImportError next time.
        """
        if getattr(self, "_ffug_table", None) is None:
            self._ffug_table = self.resource(DOCUMENT_STORE).Table(TABLE_NAME)
        return self._ffug_table


def _active_projection(director: FfugDirector) -> dict[str, Any]:
    """The tenant's projection row, or a typed refusal.

    Three refusals, deliberately distinguishable — from a caller's point of view
    they all mean "no", but they mean very different things to whoever is
    holding the pager:

    * ``tenant_not_provisioned`` — the bus event has not arrived (or never will,
      because ffug was deployed after the tenant existed and no lifecycle event
      has been emitted since).
    * ``tenant_not_active`` — suspended. TS-MC.8: refusal happens on receipt of
      the suspension, so the contamination window is event-delivery latency.
    * ``tenant_not_active`` with no salt — the stripped marker left by
      ``tenant.deleted``. Reached only by a caller holding a still-valid envelope
      for a tenant deleted moments ago.
    """
    environment, tenant_id = director.environment, director.tenant_id
    row = director.table.get_item(
        Key=keys.projection_key(environment, tenant_id)
    ).get("Item")

    if row is None:
        raise FfugError(
            "tenant_not_provisioned",
            "no projection for this tenant — ffug has seen no lifecycle event for it",
        )
    status = row.get("status")
    if status != "active":
        raise FfugError("tenant_not_active", f"tenant is {status!r}, not active")
    if not row.get("prime"):
        raise FfugError("tenant_not_active", "tenant has no salt")
    return row


def _op_echo(event: dict[str, Any], director: FfugDirector) -> dict[str, Any]:
    item_id = (event.get("item_id") or "").strip()
    if not item_id:
        raise FfugError("missing_item_id", "item_id is required for echo")
    payload = event.get("payload")
    if payload is None:
        raise FfugError("missing_payload", "payload is required for echo")

    _active_projection(director)
    item = {
        **keys.item_key(director.environment, director.tenant_id, item_id),
        "payload": payload,
    }
    director.table.put_item(Item=item)
    return {"ok": True, "operation": "echo", "item_id": item_id, "payload": payload}


def _op_get(event: dict[str, Any], director: FfugDirector) -> dict[str, Any]:
    item_id = (event.get("item_id") or "").strip()
    if not item_id:
        raise FfugError("missing_item_id", "item_id is required for get")

    _active_projection(director)
    result = director.table.get_item(
        Key=keys.item_key(director.environment, director.tenant_id, item_id)
    )
    item = result.get("Item")
    if item is None:
        raise FfugError("not_found", f"no item {item_id} for this tenant")
    return {"ok": True, "operation": "get", "item_id": item_id, "payload": item.get("payload")}


def _op_hash(event: dict[str, Any], director: FfugDirector) -> dict[str, Any]:
    """Return this tenant's digest of *payload*. Stores nothing.

    The same payload under two tenants yields two digests because the salts
    differ. The interesting half is not that they differ — it is that neither
    invocation *could* have produced the other's, because the read one line
    below is bounded by this request's narrowed credentials to this request's
    tenant partition.

    ``prime`` is returned alongside the digest on purpose. It is not a secret
    (see salt.py), and handing it back makes the demo reproducible by hand:
    anyone can confirm the digest is what it claims to be.
    """
    payload = event.get("payload")
    if payload is None:
        raise FfugError("missing_payload", "payload is required for hash")

    prime = str(_active_projection(director)["prime"])
    return {
        "ok": True,
        "operation": "hash",
        "prime": prime,
        "digest": salt.digest(prime, payload),
    }


_OPS = {"echo": _op_echo, "get": _op_get, "hash": _op_hash}


def _build_director(event: dict[str, Any], context: Any) -> FfugDirector:
    """Construct the Director, translating its refusals into typed rejections.

    Every branch here is a REFUSAL, returned as data so UAT-4 can assert on the
    rejection class rather than parse a stack trace. Note what is deliberately
    absent: a branch for narrowing failure. That is a deployment fault, not a
    caller fault, so it propagates and the invocation errors — an operator
    should see it, and a caller should not be told anything useful about it.

    ``reason_code`` comes off the library's own exceptions, so ffug's codes and
    Porth's audit-log codes are the same vocabulary. The Director has already
    written the H4 rejection line by the time we get here; this only shapes the
    reply.
    """
    try:
        return FfugDirector(event, context)
    except EnvelopeError as exc:
        raise FfugError(getattr(exc, "reason_code", "envelope_error"), str(exc)) from exc
    except (UnknownServiceError, ServiceNotActiveError) as exc:
        # The signature verified; the service it names is not one this install
        # will accept calls from. A different fault from a bad signature, and
        # worth its own code — one is forgery, the other is configuration.
        raise FfugError("source_service_refused", str(exc)) from exc
    except ServicesConfigError as exc:
        raise FfugError("services_config_unreadable", str(exc)) from exc


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    event = event or {}
    try:
        director = _build_director(event, context)

        if not director.is_authenticated:
            # No envelope at all, or one carrying no tenant. Refused rather than
            # served under a default — the fail-closed posture ffug has had
            # since Phase A, now applied to a boundary that can be forged.
            raise FfugError(
                "missing_context",
                "no verified tenant context on this invocation",
            )

        # `operation`, the D7.4 wire field. ServiceClient sends
        # {"operation", "payload", "porth_context"}, so a service that reads
        # `op` can be called by hand and not by the sanctioned client — which is
        # the wrong way round, since the client is the supported route and the
        # hand-rolled invoke is the one being designed out (PORTH-599).
        op = (event.get("operation") or "echo").strip()
        fn = _OPS.get(op)
        if fn is None:
            raise FfugError("unknown_op", f"unknown op {op!r}")

        result = fn(event, director)
        log.info(
            "ffug.served operation=%s environment=%s tenant_id=%s source_service=%s trace_id=%s",
            op,
            director.environment,
            director.tenant_id,
            director.source_service or "-",
            director.trace_id or "-",
        )
        return result
    except FfugError as exc:
        return exc.to_response()
