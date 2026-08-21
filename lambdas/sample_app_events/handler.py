from __future__ import annotations
import logging
import os
import boto3

# PORTH-594 — this consumer writes a key shape the app can no longer read.
#
# The request path moved to ``ENV#{slot}#TENANT#{tenant}``; these writes are
# still ``TENANT#{tenant}`` and ``PLATFORM``. Deliberately not migrated with it,
# for two reasons worth stating rather than leaving to be inferred:
#
#   1. This rule has almost certainly never fired. It matches source
#      ``porth.components`` on the DEFAULT bus; Porth emits
#      ``porth.user-management`` on ``porth-events-{branch}``. PORTH-588 covers
#      it, and its first question is whether this function should exist at all —
#      nothing reads USER_CACHE# or TENANT_CACHE#, so it may simply be deleted.
#
#   2. It has no Director. No authorizer runs for an EventBridge delivery, so
#      where it would get the ADR-Z8 slot from is a real decision that depends
#      on which channel PORTH-588 puts it on. Guessing now would bake the wrong
#      answer into a function that does not run.
#
# The rows it would write are unreachable under the current session policy —
# harmless while nothing reads them and nothing writes them, a bug the moment
# either changes. Hence this comment rather than silence.
logger = logging.getLogger(__name__)
TABLE_NAME = f"porth-sample-app-{os.environ.get('PORTH_ENVIRONMENT', 'dev')}"
_table = None

def _get_table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1")).Table(TABLE_NAME)
    return _table

def handler(event: dict, context) -> None:
    detail = event.get("detail", {})
    entity_type = detail.get("entity_type")
    action = detail.get("action")
    after = detail.get("after") or {}
    metadata = detail.get("metadata") or {}
    tenant_id = metadata.get("tenant_id") or after.get("tenant_id")
    entity_id = detail.get("entity_id")
    timestamp = detail.get("timestamp", "")
    table = _get_table()

    if entity_type == "User" and action in ("created", "updated") and tenant_id:
        logger.info("Caching user %s for tenant %s", entity_id, tenant_id)
        table.put_item(Item={
            "pk": f"TENANT#{tenant_id}", "sk": f"USER_CACHE#{entity_id}",
            "display_name": after.get("display_name"), "email": after.get("email"),
            "status": after.get("status"), "updated_at": timestamp,
        })
    elif entity_type == "Tenant" and action in ("created", "updated") and tenant_id:
        logger.info("Caching tenant %s", tenant_id)
        table.put_item(Item={
            "pk": "PLATFORM", "sk": f"TENANT_CACHE#{tenant_id}",
            "display_name": after.get("display_name"), "status": after.get("status"),
            "updated_at": timestamp,
        })
    else:
        logger.debug("Ignoring event entity_type=%s action=%s", entity_type, action)
