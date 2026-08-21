"""ffug's tenant projection, fed from the lifecycle bus (PORTH-587, ADR-Z11 D9).

The point of this module, in one sentence: **a tenant acquires its identity in
ffug without anybody calling ffug.** Porth emits ``tenant.created`` on the
env-aware event plane, this consumer mints that tenant's salt, and by the time a
caller arrives the row is already there. That is what "tenant isolation spans
into background services" means concretely — the isolation boundary is
established by a background subscription, not by the first request.

``porth_common.events.tenant_lifecycle.TenantProjection`` is the reference
consumer for the mandatory discipline (PORTH-546). It is **in memory**, so it
cannot survive a Lambda invocation; what follows is the same five rules made
durable in DynamoDB, and the mapping is worth stating because a reader will
otherwise assume the library is being ignored:

===========================  =================================================
reference (in memory)        here (DynamoDB)
===========================  =================================================
``_seen`` dedupe set         the conditional write — a re-delivered event has an
                             equal ``occurred_at``, so ``<`` is false and the
                             write is a no-op. No set to grow, no TTL to tune.
``occurred_at`` version gate the same condition, doing double duty
``_deleted_at`` order gate   the stripped, TTL'd row left by ``tenant.deleted``
``on_purge`` hooks           :func:`_purge_domain_rows`, inline
``on_invalidate`` hooks      N/A — ffug holds no warm cache of tenant state; it
                             reads the projection per invocation
``seed()`` bulk seed         not implemented (out of scope, PORTH-587): any
                             lifecycle event provisions a missing tenant, so a
                             reset-and-reseed rebuilds the projection
===========================  =================================================

Public-repo note (PORTH-533): this repo's Actions logs are world-readable. Log
identifiers only — never the salt, never a payload.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

from porth_common.events.tenant_lifecycle import (
    TenantLifecycleContractError,
    TenantLifecycleEvent,
)

from . import keys, salt

log = logging.getLogger(__name__)
log.setLevel(os.environ.get("FFUG_LOG_LEVEL", "INFO"))

TABLE_NAME = os.environ.get("FFUG_TABLE_NAME", "")

#: How long the stripped marker left by ``tenant.deleted`` survives. It exists
#: only to refuse a late pre-deletion event, and EventBridge redelivery is
#: measured in minutes, so a week is generous by three orders of magnitude.
#: Bounded rather than permanent because a marker that never expires IS residue.
TOMBSTONE_TTL_SECONDS = 7 * 24 * 60 * 60

#: Mirrors ``_STATUS_AFTER`` in porth_common.events.tenant_lifecycle. Kept local
#: rather than imported because that name is private; if the library's mapping
#: changes, this is the site to grep for.
_STATUS_AFTER = {"created": "active", "reactivated": "active", "suspended": "suspended"}

_table = None


def _get_table():
    """Module-level handle, built once per warm container.

    Same convention as ``sample_app_events``: a client constructed inside the
    handler is rebuilt on every invocation and reuses no connection.
    """
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(TABLE_NAME)
    return _table


def _conditional_check_failed(exc: Exception) -> bool:
    """True when DynamoDB refused the write because our order gate said so.

    Matched on the modelled exception where boto3 offers one, and on the error
    code otherwise — the resource-level ``Table`` does not expose ``meta.client``
    exceptions in every botocore version, and a string match on the message
    would break on a wording change.
    """
    code = getattr(exc, "response", {}).get("Error", {}).get("Code")
    return code == "ConditionalCheckFailedException"


def _apply_status(event: TenantLifecycleEvent) -> dict[str, Any]:
    """Upsert the tenant's projection row, minting its salt if it has none.

    One write does four jobs: seeds an unknown tenant, refreshes a known one,
    de-duplicates a re-delivery and rejects a stale event. That is the whole
    ordering discipline, expressed as a condition rather than as a read-then-write
    — which under at-least-once delivery would race with itself.

    ``if_not_exists(prime, ...)`` is the load-bearing clause. A re-delivered
    ``tenant.created`` that re-minted the salt would silently change every digest
    ffug has ever returned for that tenant, and nothing would report it: the
    service would keep working and keep answering differently.

    A tenant first seen on ``updated`` or ``suspended`` is provisioned here too.
    That is deliberate self-healing — ffug deployed after a tenant existed should
    converge on the next event it sees rather than stay permanently blind to it.
    """
    status = _STATUS_AFTER.get(event.action) or event.data.get("status") or "active"

    return _get_table().update_item(
        Key=keys.projection_key(event.environment, event.tenant_id),
        UpdateExpression=(
            "SET #status = :status, #occurred_at = :occurred_at, "
            "#environment = :environment, #tenant_id = :tenant_id, "
            "#prime = if_not_exists(#prime, :prime) "
            "REMOVE #expires_at"
        ),
        # Every name aliased. Only #status is currently a DynamoDB reserved
        # word, but the reserved list has ~570 entries and grows, and the
        # failure is a ValidationException at runtime on a path that is only
        # exercised by real events.
        ExpressionAttributeNames={
            "#status": "status",
            "#occurred_at": "occurred_at",
            "#environment": "environment",
            "#tenant_id": "tenant_id",
            "#prime": "prime",
            "#expires_at": "expires_at",
        },
        ExpressionAttributeValues={
            ":status": status,
            ":occurred_at": event.occurred_at,
            ":environment": event.environment,
            ":tenant_id": event.tenant_id,
            ":prime": salt.mint_prime(),
        },
        # A deletion is terminal for anything at or before it: the marker it
        # leaves carries the deletion's timestamp, so a late pre-deletion event
        # fails this and cannot resurrect the tenant.
        ConditionExpression="attribute_not_exists(pk) OR #occurred_at < :occurred_at",
    )


def _purge(event: TenantLifecycleEvent) -> None:
    """Residue-free teardown on both sides (Q6 cascade).

    Order matters. The marker is written FIRST: if the domain purge fails
    halfway, the retry finds a tenant already closed for business rather than
    one that looks active and is missing half its rows.
    """
    now_expiry = int(_utc_epoch()) + TOMBSTONE_TTL_SECONDS

    _get_table().update_item(
        Key=keys.projection_key(event.environment, event.tenant_id),
        # The salt is REMOVEd, not overwritten. What is left names a tenant and
        # a time and nothing else — see the residue definition on PORTH-587.
        UpdateExpression=(
            "SET #status = :deleted, #occurred_at = :occurred_at, "
            "#environment = :environment, #tenant_id = :tenant_id, "
            "#expires_at = :expires_at "
            "REMOVE #prime"
        ),
        ExpressionAttributeNames={
            "#status": "status",
            "#occurred_at": "occurred_at",
            "#environment": "environment",
            "#tenant_id": "tenant_id",
            "#prime": "prime",
            "#expires_at": "expires_at",
        },
        ExpressionAttributeValues={
            ":deleted": "deleted",
            ":occurred_at": event.occurred_at,
            ":environment": event.environment,
            ":tenant_id": event.tenant_id,
            ":expires_at": now_expiry,
        },
        ConditionExpression="attribute_not_exists(pk) OR #occurred_at < :occurred_at",
    )
    _purge_domain_rows(event.environment, event.tenant_id)


def _purge_domain_rows(environment: str, tenant_id: str) -> int:
    """Delete every ``ITEM#`` row in the tenant's partition. Returns the count.

    Paginated on ``LastEvaluatedKey`` and projected to the keys alone: this is
    transient data with no bound on how much of it one tenant accumulated, and
    fetching whole items to throw them away would page in payloads we have no
    reason to read (and must not log).
    """
    table = _get_table()
    partition = keys.partition(environment, tenant_id)
    deleted = 0
    start_key: dict[str, Any] | None = None

    while True:
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("pk").eq(partition)
            & Key("sk").begins_with(keys.ITEM_SK_PREFIX),
            "ProjectionExpression": "pk, sk",
        }
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key

        page = table.query(**kwargs)
        rows = page.get("Items", [])
        if rows:
            with table.batch_writer() as batch:
                for row in rows:
                    batch.delete_item(Key={"pk": row["pk"], "sk": row["sk"]})
                    deleted += 1

        start_key = page.get("LastEvaluatedKey")
        if not start_key:
            return deleted


def _utc_epoch() -> float:
    """Seconds since the epoch. Wrapped so tests can freeze it."""
    import time

    return time.time()


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    """One EventBridge delivery.

    Return values are for tests and logs; EventBridge ignores them. What matters
    is which failures RAISE, because raising is what asks for a redelivery:

    * contract violation — malformed, wrong version, detail-type/action
      mismatch. Redelivering will not make it well-formed, so it is logged and
      swallowed. Raising would loop the same bad event until the retry budget
      is spent and then bury it, which is worse than one WARNING.
    * order gate refused the write — the expected outcome for a duplicate or a
      stale event. Not an error at all.
    * anything else — DynamoDB throttled, credentials lapsed, table missing.
      Raised, so the delivery is retried.
    """
    event = event or {}
    detail_type = event.get("detail-type") or ""
    detail = event.get("detail") or {}

    try:
        lifecycle = TenantLifecycleEvent.from_detail(detail_type, detail)
    except TenantLifecycleContractError as exc:
        log.warning("ffug.lifecycle.refused detail_type=%s reason=%s", detail_type, exc)
        return {"ok": False, "reason": "contract_violation"}

    try:
        if lifecycle.action == "deleted":
            _purge(lifecycle)
        else:
            _apply_status(lifecycle)
    except Exception as exc:  # noqa: BLE001 — re-raised below unless it is the gate
        if not _conditional_check_failed(exc):
            raise
        log.info(
            "ffug.lifecycle.ignored action=%s environment=%s tenant_id=%s "
            "occurred_at=%s reason=duplicate_or_stale",
            lifecycle.action,
            lifecycle.environment,
            lifecycle.tenant_id,
            lifecycle.occurred_at,
        )
        return {"ok": True, "applied": False, "reason": "duplicate_or_stale"}

    log.info(
        "ffug.lifecycle.applied action=%s environment=%s tenant_id=%s occurred_at=%s",
        lifecycle.action,
        lifecycle.environment,
        lifecycle.tenant_id,
        lifecycle.occurred_at,
    )
    return {"ok": True, "applied": True, "action": lifecycle.action}
