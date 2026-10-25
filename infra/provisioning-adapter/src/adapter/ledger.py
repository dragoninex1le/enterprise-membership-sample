"""What this adapter wrote, by run - the label that makes `teardown` work (D6, §4.7).

Porth's rows have nowhere to carry a run id, so the label lives beside them - in **prawf's own
audit table** (`prawf-adapter-audit`, template.yml), never in Porth's. A test tool's bookkeeping in
the application's tables is state the application never agreed to hold, read by code that never
expected it (Richard, 2026-10-25). Nothing here is ever written to a Porth table.

One partition per slot and entity, `PK = ENV#{s}#ENTITY#{entity}`:

* `SK = RUN#{run_id}` - what a run wrote to the entity, appended **before** the write it records, so
  a seed that fails half way leaves a ledger that still covers everything it might have written.
  Teardown removes what is listed and tolerates what is already gone. An entry is either an exact
  `item` (table and key), or a `tenant` scope - every row under a tenant the run itself created, for
  writes whose keys Porth generates (a role's id) and so cannot be noted in advance.
* `SK = DATASET` - which dataset the entity carries, so the same id and version seeded again is
  `unchanged` and a different one is refused (§8.4).

Every partition key starts `ENV#{s}#`, so the one-slot session reaches this slot's rows and no
other's, here as in Porth's tables.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone


def _table() -> str:
    return os.environ["PRAWF_AUDIT_TABLE"]


def _pk(env_scope: str, entity: str) -> dict:
    return {"S": f"ENV#{env_scope}#ENTITY#{entity}"}


def run_key(env_scope: str, run_id: str, entity: str) -> dict:
    return {"PK": _pk(env_scope, entity), "SK": {"S": f"RUN#{run_id}"}}


def marker_key(env_scope: str, entity: str) -> dict:
    return {"PK": _pk(env_scope, entity), "SK": {"S": "DATASET"}}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def marker(db, env_scope: str, entity: str) -> dict | None:
    item = db.get_item(TableName=_table(), Key=marker_key(env_scope, entity), ConsistentRead=True).get("Item")
    if not item:
        return None
    return {k: v["S"] for k, v in item.items() if "S" in v}


def set_marker(db, env_scope: str, entity: str, dataset: dict, run_id: str, handles: list[dict]) -> None:
    db.put_item(TableName=_table(), Item={
        **marker_key(env_scope, entity),
        "dataset_id": {"S": dataset["id"]},
        "version": {"S": dataset["version"]},
        "digest": {"S": dataset["digest"]},
        "run_id": {"S": run_id},
        "handles": {"S": json.dumps(handles, separators=(",", ":"))},
        "applied_at": {"S": _now()},
    })


def item(table: str, key: dict) -> dict:
    """An exact row. `key` is plain: `{"PK": "...", "SK": "..."}` or `{"pk": ..., "sk": ...}`."""
    return {"kind": "item", "table": table, "key": key}


def tenant_scope(tenant_id: str) -> dict:
    """Every role, grant and permission row under a tenant this run created."""
    return {"kind": "tenant", "tenant_id": tenant_id}


def record(db, env_scope: str, run_id: str, entity: str, entry: dict) -> None:
    """Note a write before making it."""
    db.update_item(
        TableName=_table(),
        Key=run_key(env_scope, run_id, entity),
        UpdateExpression="SET writes = list_append(if_not_exists(writes, :empty), :w), "
                         "run_id = :run, started_at = if_not_exists(started_at, :now)",
        ExpressionAttributeValues={
            ":w": {"L": [{"S": json.dumps(entry, sort_keys=True)}]},
            ":empty": {"L": []},
            ":run": {"S": run_id},
            ":now": {"S": _now()},
        },
    )


def writes(db, env_scope: str, run_id: str, entity: str) -> list[dict] | None:
    """What a run wrote to an entity, in the order recorded - or None if it wrote nothing there."""
    found = db.get_item(TableName=_table(), Key=run_key(env_scope, run_id, entity), ConsistentRead=True).get("Item")
    if not found:
        return None
    return [json.loads(w["S"]) for w in found.get("writes", {}).get("L", [])]


def forget(db, env_scope: str, run_id: str, entity: str) -> None:
    """Drop a run's ledger for an entity, and the dataset marker if this run set it."""
    current = marker(db, env_scope, entity)
    if current and current.get("run_id") == run_id:
        db.delete_item(TableName=_table(), Key=marker_key(env_scope, entity))
    db.delete_item(TableName=_table(), Key=run_key(env_scope, run_id, entity))


def forget_entity(db, env_scope: str, entity: str) -> int:
    """Reset: every run's ledger for the entity, and its marker - its rows are gone, whoever wrote them."""
    kwargs = {"TableName": _table(), "KeyConditionExpression": "PK = :pk",
              "ExpressionAttributeValues": {":pk": _pk(env_scope, entity)}, "ConsistentRead": True}
    removed, start = 0, None
    while True:
        if start:
            kwargs["ExclusiveStartKey"] = start
        page = db.query(**kwargs)
        for row in page.get("Items", []):
            db.delete_item(TableName=_table(), Key={"PK": row["PK"], "SK": row["SK"]})
            removed += 1
        start = page.get("LastEvaluatedKey")
        if not start:
            return removed
