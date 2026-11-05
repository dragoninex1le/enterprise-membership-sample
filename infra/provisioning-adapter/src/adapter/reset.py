"""`reset` - return the slot to what was bootstrapped (PRF-14, contract 1.1).

PROVISIONING-CONTRACT §4.4: reset clears seeded data and anything the tests created, and leaves the
install as it was bootstrapped, not empty (C12). Back to *seeded* is reset then seed of the same
dataset (PRF-14, rewritten 2026-11-05).

Two entities reset:

* `porth` - every row of the slot in Porth's tables goes, and the baseline prawf names comes back
  (snapshot.py). Whatever a seed or a test changed - a tenant, a role, an IdP config on the platform
  tenant - is gone, and anything a test still needs is seeded again (Richard, 2026-11-05). The seed
  entities' ledgers go with their rows, so the same dataset seeded again is written, not `unchanged`.
* `porth-session` - every row in Porth's sessions table. Sessions carry no environment in their keys,
  so this one is not held to the slot: it logs everyone out of every environment on this install
  (Richard, 2026-11-04). It reads only the keys of the rows it deletes - never a token.

**What reset still knows about Porth: its events.** Porth's consumers hear that a tenant has gone
only from Porth's `deleted` events - FFUG keeps a tenant's data until one arrives. A row removed
without its event leaves them stale, so a tenant, organisation or user that reset removes, and does
not write back, is announced the way Porth's own delete would announce it.

**Guarded twice.** A `protected` slot refuses reset outright (C8, D5). On a disposable one the
caller must say what it believes the slot to be (`confirm_environment_class`) and is refused on a
mismatch - a mistake-detector, never an authorisation: the slot's class decides.

A dry run says what would go and changes nothing (C14).
"""
from __future__ import annotations

import os

import ledger
import porth_claim_mapping
import porth_org
import porth_role
import porth_tenant
import snapshot
from envelope import ContractError
from porth_tenant import Porth

SESSION = "porth-session"
#: Their rows are the slot's rows: when the slot goes back to its baseline, their ledgers go too.
SEEDED = (porth_org.ENTITY, porth_tenant.ENTITY, porth_role.ENTITY, porth_claim_mapping.ENTITY)


def confirm(slot_cfg: dict, payload: object) -> None:
    klass = slot_cfg["environment_class"]
    if klass == "protected":
        raise ContractError("refused", "environment_protected", "this slot is protected; reset is not permitted on any entity")
    claimed = payload.get("confirm_environment_class") if isinstance(payload, dict) else None
    if claimed is None:
        raise ContractError(
            "refused", "scope_violation",
            "reset needs payload.confirm_environment_class: what you believe this slot to be (§4.4)",
        )
    if claimed != klass:
        raise ContractError(
            "refused", "scope_violation",
            f"the caller believes this slot is {claimed!r}; it is {klass!r}. Nothing was reset",
        )


def _announcer(porth: Porth, env_scope: str):
    """Porth's `deleted` events for the rows reset removes and does not write back."""
    prefix = f"ENV#{env_scope}#"
    said = []

    def publish(table: str, row: dict) -> None:
        if table == "tenants" and row.get("SK", {}).get("S") == "METADATA":
            rest = row["PK"]["S"].removeprefix(prefix)
            if rest.startswith("TENANT#"):
                tid = rest.removeprefix("TENANT#")
                porth.publisher.publish(entity_type="Tenant", action="deleted", entity_id=tid, metadata={"tenant_id": tid})
                porth.publisher.publish_tenant_lifecycle(action="deleted", tenant_id=tid)
                said.append(f"tenant {tid}")
            elif rest.startswith("ORG#"):
                org_id = rest.removeprefix("ORG#")
                porth.publisher.publish(entity_type="Organization", action="deleted", entity_id=org_id,
                                        metadata={"organization_id": org_id})
                said.append(f"organisation {org_id}")
        elif table == "users" and "#USER#" in row.get("PK", {}).get("S", ""):
            tid = row["PK"]["S"].removeprefix(prefix).removeprefix("TENANT#").split("#", 1)[0]
            uid = row.get("id", {}).get("S") or row["PK"]["S"].rsplit("#USER#", 1)[1]
            porth.publisher.publish(entity_type="User", action="deleted", entity_id=uid, metadata={"tenant_id": tid})
            said.append("user")

    return publish, said


def _porth(slot_cfg: dict, run_id: str, dry_run: bool, payload: object) -> tuple[list[dict], list[str]]:
    env_scope = slot_cfg["env_scope"]
    if dry_run:
        return snapshot.restore(env_scope, run_id, True, payload, lambda *_: None)
    porth = Porth(env_scope, run_id)
    publish, said = _announcer(porth, env_scope)
    results, notes = snapshot.restore(env_scope, run_id, False, payload, publish)
    forgotten = sum(ledger.forget_entity(porth.db, env_scope, e) for e in SEEDED)
    users = said.count("user")
    named = [s for s in said if s != "user"]
    notes.append(f"announced deleted: {', '.join(named) or 'no tenant or organisation'}"
                 + (f", {users} user(s)" if users else ""))
    notes.append(f"forgot {forgotten} ledger record(s) of the seed entities")
    return results, notes


def _sessions(slot_cfg: dict, run_id: str, dry_run: bool) -> tuple[list[dict], list[str]]:
    porth = Porth(slot_cfg["env_scope"], run_id)
    table = os.environ["PORTH_SESSIONS_TABLE"]
    keys = [k["AttributeName"] for k in porth.db.describe_table(TableName=table)["Table"]["KeySchema"]]
    names = {f"#k{n}": k for n, k in enumerate(keys)}
    scan = {"TableName": table, "ProjectionExpression": ", ".join(names), "ExpressionAttributeNames": names}
    count, start = 0, None
    while True:
        page = porth.db.scan(**scan, **({"ExclusiveStartKey": start} if start else {}))
        for row in page.get("Items", []):
            count += 1
            if not dry_run:
                porth.db.delete_item(TableName=table, Key=row)
        start = page.get("LastEvaluatedKey")
        if not start:
            break
    return [], [f"{SESSION}: {'would remove' if dry_run else 'removed'} {count} session(s), in every environment on this install"]


RESETS = (snapshot.ENTITY, SESSION)


def reset(entity: str, slot_cfg: dict, run_id: str, dry_run: bool, payload: object) -> tuple[list[dict], list[str]]:
    confirm(slot_cfg, payload)
    if entity == SESSION:
        return _sessions(slot_cfg, run_id, dry_run)
    return _porth(slot_cfg, run_id, dry_run, payload)
