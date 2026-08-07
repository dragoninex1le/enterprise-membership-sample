"""ffug — a deliberately dumb consuming service (ADR-Z11 PORTH-555, Phase A).

Echo-with-storage and nothing else. ffug exists so the Services Area has a real
deployed callee to be tested *against*; it is not a product and never gains one.
See README.md in this directory for the boundary rules a reviewer asserts.

Phase A (this file today): plain IAM invoke, no porth-common. Tenant context
arrives on the payload and is trusted only because the caller had to hold
`lambda:InvokeFunction` to get here at all.

Phase B: `resolve_tenant_context` is the single seam that changes — it will
verify the KMS-signed context envelope (PORTH-547) and derive tenant/environment
from the verified token instead of the payload. Nothing else in this module
should need to move.

Public-repo note (PORTH-533): this repo is public and its Actions logs are
world-readable. Log identifiers, never payload bodies.
"""

from __future__ import annotations

import os
from typing import Any

import boto3

TABLE_NAME = os.environ.get("FFUG_TABLE_NAME", "")

# Lazy module-level handle so tests can substitute a double, matching the
# sample_app_events convention in this repo.
_table = None


def _get_table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(TABLE_NAME)
    return _table


class FfugError(Exception):
    """Typed rejection. Carries an HTTP-ish code so callers can assert on it."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_response(self) -> dict[str, Any]:
        return {"ok": False, "error": {"code": self.code, "message": self.message}}


def resolve_tenant_context(event: dict[str, Any]) -> tuple[str, str]:
    """Return (environment, tenant_id) for this invocation.

    PHASE B SWAP POINT — replaced by envelope verification (PORTH-547). Until
    then the values ride the payload. Both are mandatory and there is no default:
    a caller that omits either is refused rather than served under a fallback
    tenant, so the fail-closed posture is true from Phase A onward.
    """
    environment = (event.get("environment") or "").strip()
    tenant_id = (event.get("tenant_id") or "").strip()
    if not environment:
        raise FfugError("missing_environment", "environment is required")
    if not tenant_id:
        raise FfugError("missing_tenant", "tenant_id is required")
    return environment, tenant_id


def _keys(environment: str, tenant_id: str, item_id: str) -> dict[str, str]:
    """ADR-Z8 key shape: every row sits under its env+tenant prefix."""
    return {"pk": f"ENV#{environment}#TENANT#{tenant_id}", "sk": f"ITEM#{item_id}"}


def _op_echo(event: dict[str, Any], environment: str, tenant_id: str) -> dict[str, Any]:
    item_id = (event.get("item_id") or "").strip()
    if not item_id:
        raise FfugError("missing_item_id", "item_id is required for echo")
    payload = event.get("payload")
    if payload is None:
        raise FfugError("missing_payload", "payload is required for echo")

    item = {**_keys(environment, tenant_id, item_id), "payload": payload}
    _get_table().put_item(Item=item)
    return {"ok": True, "op": "echo", "item_id": item_id, "payload": payload}


def _op_get(event: dict[str, Any], environment: str, tenant_id: str) -> dict[str, Any]:
    item_id = (event.get("item_id") or "").strip()
    if not item_id:
        raise FfugError("missing_item_id", "item_id is required for get")

    result = _get_table().get_item(Key=_keys(environment, tenant_id, item_id))
    item = result.get("Item")
    if item is None:
        raise FfugError("not_found", f"no item {item_id} for this tenant")
    return {"ok": True, "op": "get", "item_id": item_id, "payload": item.get("payload")}


_OPS = {"echo": _op_echo, "get": _op_get}


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    event = event or {}
    try:
        environment, tenant_id = resolve_tenant_context(event)
        op = (event.get("op") or "echo").strip()
        fn = _OPS.get(op)
        if fn is None:
            raise FfugError("unknown_op", f"unknown op {op!r}")
        return fn(event, environment, tenant_id)
    except FfugError as exc:
        return exc.to_response()
