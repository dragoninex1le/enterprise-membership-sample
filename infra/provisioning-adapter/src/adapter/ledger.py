"""What this adapter wrote, by run - the label that makes `teardown` work (D6, §4.7).

Porth's rows have nowhere to carry a run id, so the label lives beside them: a ledger, in the slot's
own tenants table, under keys Porth never reads.

* `PK = ENV#{s}#PRAWF#RUN#{run_id}`, `SK = LEDGER#{entity}` - what a run wrote for an entity,
  appended **before** the write it records, so a seed that fails half way leaves a ledger that
  still covers everything it might have written. Teardown removes what is listed and tolerates
  what is already gone. An entry is either an exact `item` (table and key), or a `tenant` scope -
  every row under a tenant the run itself created, for writes whose keys Porth generates (a role's
  id) and so cannot be noted in advance.
* `PK = ENV#{s}#PRAWF#DATASET#{entity}`, `SK = CURRENT` - which dataset the entity carries, so the
  same id and version seeded again is `unchanged` and a different one is refused (§8.4).

**Why these keys are safe in Porth's table.** Porth's tenant directory scans the tenants table for
`SK = METADATA AND contains(PK, "TENANT#")` (porth-common `list_all_with_environment`) - a row that
matched and failed validation would empty the directory and stop every login in the slot. Neither
key here can match: no `TENANT#` in the partition key, never `METADATA` as the sort key. Neither
carries a `gsi1pk` or `gsi2pk`, so no Porth index lists them either. Every partition key starts
`ENV#{s}#`, so the one-slot session reaches them and nothing else.
"""
from __future__ import annotations

import json
import os


def _table() -> str:
    return os.environ["PORTH_TENANTS_TABLE"]


def run_key(env_scope: str, run_id: str, entity: str) -> dict:
    return {"PK": {"S": f"ENV#{env_scope}#PRAWF#RUN#{run_id}"}, "SK": {"S": f"LEDGER#{entity}"}}


def marker_key(env_scope: str, entity: str) -> dict:
    return {"PK": {"S": f"ENV#{env_scope}#PRAWF#DATASET#{entity}"}, "SK": {"S": "CURRENT"}}


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
        UpdateExpression="SET writes = list_append(if_not_exists(writes, :empty), :w)",
        ExpressionAttributeValues={
            ":w": {"L": [{"S": json.dumps(entry, sort_keys=True)}]},
            ":empty": {"L": []},
        },
    )


def runs(db, env_scope: str, run_id: str) -> list[tuple[str, list[dict]]]:
    """Every entity this run wrote to, with its entries in the order they were recorded."""
    items = db.query(
        TableName=_table(),
        KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
        ExpressionAttributeValues={":pk": {"S": f"ENV#{env_scope}#PRAWF#RUN#{run_id}"}, ":sk": {"S": "LEDGER#"}},
        ConsistentRead=True,
    ).get("Items", [])
    out = []
    for item in items:
        entity = item["SK"]["S"].removeprefix("LEDGER#")
        writes = [json.loads(w["S"]) for w in item.get("writes", {}).get("L", [])]
        out.append((entity, writes))
    return out


def forget(db, env_scope: str, run_id: str, entity: str) -> None:
    """Drop a run's ledger for an entity, and the dataset marker if this run set it."""
    current = marker(db, env_scope, entity)
    if current and current.get("run_id") == run_id:
        db.delete_item(TableName=_table(), Key=marker_key(env_scope, entity))
    db.delete_item(TableName=_table(), Key=run_key(env_scope, run_id, entity))
