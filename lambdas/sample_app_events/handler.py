from __future__ import annotations
import logging
import os
import boto3

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
