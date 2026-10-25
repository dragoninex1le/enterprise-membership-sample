"""`reset` (PRF-14) - return an entity to its bootstrapped state, whoever wrote what is there.

PROVISIONING-CONTRACT §4.4: reset clears seeded data and anything the tests created, and leaves the
entity bootstrapped, not empty (C12). It is what §8.4 sends a caller to when a seed meets data it did
not write - which teardown cannot reach, because teardown removes only what a run labelled.

**What bootstrapped means here.** The platform baseline - the platform tenant, its organisation,
roles, permissions and claim mapping (`porth-platform`, porth_platform.py). Reset never touches it:
`porth-platform` is not resettable, and resetting one entity leaves the others alone (C16). Each
resettable entity's baseline is therefore *none of its own rows*:

* `porth-claim-mapping` - every claim-mapping version of every tenant except the platform's;
* `porth-tenant` - every tenant except the platform, with its roles, grants and permissions (both
  grant key shapes, PORTH-604) and its IdP config, which lives on the tenant row;
* `porth-org` - every organisation except the platform's. Refused while tenants still belong to one:
  reset `porth-tenant` first, which reset with no entity does.

With no entity, all three, in that order - claim mappings are found through the tenants they belong
to, and an organisation cannot go while it has tenants.

**Finding what is there.** Porth's tenant directory finds tenants by scanning the tenants table, and
so does this: a tenant written without Porth's list index (gsi2) - which the old testbed seeder never
wrote - is still a tenant every login loads. The scan is the one-slot session's only Scan, on the
tenants table alone, read-only, filtered to the slot (slots.py). Roles, permissions and claim
mappings are then reached by the tenant's own keys.

**Guarded twice.** A `protected` slot refuses reset outright, on every entity (C8, D5). On a
disposable one the caller must say what it believes the slot to be (`confirm_environment_class`) and
is refused on a mismatch - a mistake-detector, never an authorisation: the slot's class decides.

**What it cannot reach** - Porth's users, org-units and sessions tables, which this adapter holds no
grant on - is named in the response rather than passed over. A dry run lists what would go and
removes nothing (C14).
"""
from __future__ import annotations

import os
from collections import defaultdict

import ledger
import porth_org
import porth_tenant
from envelope import ContractError
from porth_tenant import Porth

CLAIM_MAPPING = "porth-claim-mapping"
#: Ordered: claim mappings are found through their tenants, and tenants go before their organisations.
ORDER = (CLAIM_MAPPING, porth_tenant.ENTITY, porth_org.ENTITY)
PLATFORM = "platform"
UNREACHABLE = "Porth's users, org-units and sessions tables are outside this adapter's grant; any rows there for removed tenants remain"


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


def scan_slot(db, env_scope: str) -> list[dict]:
    """Every row of the slot in the tenants table - what Porth's directory scan sees, and more."""
    kwargs = {"TableName": os.environ["PORTH_TENANTS_TABLE"], "ConsistentRead": True,
              "FilterExpression": "begins_with(PK, :p)",
              "ExpressionAttributeValues": {":p": {"S": f"ENV#{env_scope}#"}}}
    items, start = [], None
    while True:
        if start:
            kwargs["ExclusiveStartKey"] = start
        page = db.scan(**kwargs)
        items += page.get("Items", [])
        start = page.get("LastEvaluatedKey")
        if not start:
            return items


class Slot:
    """Every row of one slot in the tenants table, by what it belongs to."""

    def __init__(self, porth: Porth, env_scope: str):
        self.porth = porth
        self.prefix = f"ENV#{env_scope}#"
        self.tenants: dict[str, list[dict]] = defaultdict(list)
        self.orgs: dict[str, list[dict]] = defaultdict(list)
        #: prawf bookkeeping an earlier adapter wrote into Porth's table (PRF-12 to PRF-14), before it
        #: had its own audit table. Reset removes it: it was never Porth's, and nothing writes it now.
        self.strays: list[dict] = []
        self.env_scope = env_scope
        for item in scan_slot(porth.db, env_scope):
            rest = item["PK"]["S"][len(self.prefix):]
            if rest.startswith("TENANT#"):
                self.tenants[rest[len("TENANT#"):].split("#", 1)[0]].append(item)
            elif rest.startswith("ORG#"):
                self.orgs[rest[len("ORG#"):].split("#", 1)[0]].append(item)
            elif rest.startswith("PRAWF#"):
                self.strays.append(item)

    def metadata(self, rows: list[dict]) -> dict | None:
        return next((r for r in rows if r["SK"]["S"] == "METADATA"), None)

    def platform_org(self) -> str | None:
        row = self.metadata(self.tenants.get(PLATFORM, []))
        return row["org_id"]["S"] if row and "org_id" in row else None

    def fixture_tenants(self) -> list[str]:
        return sorted(t for t in self.tenants if t != PLATFORM)

    def fixture_orgs(self) -> list[str]:
        platform = self.platform_org()
        out = []
        for org_id, rows in self.orgs.items():
            meta = self.metadata(rows)
            slug = meta.get("slug", {}).get("S") if meta else None
            if org_id != platform and slug != PLATFORM:
                out.append(org_id)
        return sorted(out)

    def org_label(self, org_id: str) -> str:
        meta = self.metadata(self.orgs.get(org_id, []))
        slug = meta.get("slug", {}).get("S") if meta else None
        return f"{slug} ({org_id})" if slug else org_id

    def forget(self, entity: str) -> int:
        """The entity's prawf bookkeeping goes with its rows: every run's ledger for it, and its marker."""
        return ledger.forget_entity(self.porth.db, self.env_scope, entity)

    def clear_strays(self, dry_run: bool) -> str | None:
        if not self.strays:
            return None
        if dry_run:
            return f"would remove {len(self.strays)} prawf row(s) an earlier adapter left in Porth's tenants table"
        table = os.environ["PORTH_TENANTS_TABLE"]
        for row in self.strays:
            self.porth.db.delete_item(TableName=table, Key={"PK": row["PK"], "SK": row["SK"]})
        count, self.strays = len(self.strays), []
        return f"removed {count} prawf row(s) an earlier adapter left in Porth's tenants table"


def _query(db, table: str, attr: str, value: str, index: str | None = None) -> list[dict]:
    kwargs = {"TableName": table, "KeyConditionExpression": f"{attr} = :v",
              "ExpressionAttributeValues": {":v": {"S": value}}}
    if index:
        kwargs["IndexName"] = index
    items, start = [], None
    while True:
        if start:
            kwargs["ExclusiveStartKey"] = start
        page = db.query(**kwargs)
        items += page.get("Items", [])
        start = page.get("LastEvaluatedKey")
        if not start:
            return items


def _claim_mappings(slot: Slot, env_scope: str, dry_run: bool) -> str:
    table = os.environ["PORTH_CLAIM_MAPPING_CONFIGS_TABLE"]
    found = {t: _query(slot.porth.db, table, "PK", f"ENV#{env_scope}#TENANT#{t}") for t in slot.fixture_tenants()}
    found = {t: rows for t, rows in found.items() if rows}
    count = sum(len(rows) for rows in found.values())
    if dry_run:
        return f"{CLAIM_MAPPING}: would remove {count} claim-mapping version(s) of {sorted(found) or 'no tenant'}"
    for rows in found.values():
        for row in rows:
            slot.porth.db.delete_item(TableName=table, Key={"PK": row["PK"], "SK": row["SK"]})
    slot.forget(CLAIM_MAPPING)
    return f"{CLAIM_MAPPING}: removed {count} claim-mapping version(s) of {sorted(found) or 'no tenant'}"


def _tenants(slot: Slot, env_scope: str, dry_run: bool) -> str:
    gone = slot.fixture_tenants()
    rows = sum(len(slot.tenants[t]) for t in gone)
    if dry_run:
        return f"{porth_tenant.ENTITY}: would remove tenant(s) {gone or '(none)'} - {rows} tenant row(s), with their roles, grants and permissions"
    table, roles_table, _ = porth_tenant._tables()
    for tenant_id in gone:
        # The legacy grant shape (pre PORTH-604) is keyed by role alone; find the roles first.
        role_ids = [r["sk"]["S"].removeprefix("ROLE#") for r in _query(slot.porth.db, roles_table, "pk", f"ENV#{env_scope}#TENANT#{tenant_id}")
                    if r["sk"]["S"].startswith("ROLE#")]
        porth_tenant._sweep_tenant(slot.porth, env_scope, tenant_id)
        for role_id in role_ids:
            for grant in _query(slot.porth.db, roles_table, "pk", f"ENV#{env_scope}#ROLE#{role_id}"):
                slot.porth.db.delete_item(TableName=roles_table, Key={"pk": grant["pk"], "sk": grant["sk"]})
        for row in slot.tenants.pop(tenant_id):
            slot.porth.db.delete_item(TableName=table, Key={"PK": row["PK"], "SK": row["SK"]})
        slot.porth.publisher.publish(entity_type="Tenant", action="deleted", entity_id=tenant_id,
                                     metadata={"tenant_id": tenant_id})
        slot.porth.publisher.publish_tenant_lifecycle(action="deleted", tenant_id=tenant_id)
    slot.forget(porth_tenant.ENTITY)
    return f"{porth_tenant.ENTITY}: removed tenant(s) {gone or '(none)'} - {rows} tenant row(s), with their roles, grants and permissions"


def _orgs(slot: Slot, env_scope: str, dry_run: bool) -> str:
    gone = slot.fixture_orgs()
    held = sorted({
        meta["tenant_id"]["S"] for t, rows in slot.tenants.items() if t != PLATFORM
        for meta in [slot.metadata(rows)] if meta and meta.get("org_id", {}).get("S") in gone
    })
    if held:
        raise ContractError(
            "refused", "dataset_conflict",
            f"tenant(s) {held} still belong to the organisations a reset would remove; "
            f"reset {porth_tenant.ENTITY} first (reset with no entity does)",
        )
    labels = [slot.org_label(o) for o in gone]
    if dry_run:
        return f"{porth_org.ENTITY}: would remove organisation(s) {labels or '(none)'}"
    table = os.environ["PORTH_TENANTS_TABLE"]
    for org_id in gone:
        for row in slot.orgs.pop(org_id):
            slot.porth.db.delete_item(TableName=table, Key={"PK": row["PK"], "SK": row["SK"]})
        slot.porth.publisher.publish(entity_type="Organization", action="deleted", entity_id=org_id,
                                     metadata={"organization_id": org_id})
    slot.forget(porth_org.ENTITY)
    return f"{porth_org.ENTITY}: removed organisation(s) {labels or '(none)'}"


RESETS = {CLAIM_MAPPING: _claim_mappings, porth_tenant.ENTITY: _tenants, porth_org.ENTITY: _orgs}


def reset(entity: str | None, slot_cfg: dict, run_id: str, dry_run: bool, payload: object) -> tuple[list[dict], list[str]]:
    confirm(slot_cfg, payload)
    env_scope = slot_cfg["env_scope"]
    porth = Porth(env_scope, run_id)
    slot = Slot(porth, env_scope)
    if PLATFORM not in slot.tenants:
        raise ContractError(
            "refused", "scope_violation",
            f"{env_scope} has no platform tenant: it is not bootstrapped, so there is no baseline to reset to. "
            "Bootstrap porth-platform first",
        )

    notes = []
    if dry_run:
        # A dry run of several entities reports each as if the ones before it had run.
        for name in ORDER if entity is None else (entity,):
            notes.append(RESETS[name](slot, env_scope, True))
            if name == porth_tenant.ENTITY:
                for t in slot.fixture_tenants():
                    slot.tenants.pop(t)
        stray = slot.clear_strays(True) if entity is None else None
        return [], ["dry run: nothing removed", *notes, *([stray] if stray else []), UNREACHABLE]
    for name in ORDER if entity is None else (entity,):
        notes.append(RESETS[name](slot, env_scope, False))
    # Only a full reset clears them: they are every entity's, and a scoped reset leaves the others be.
    stray = slot.clear_strays(False) if entity is None else None
    return [], [*notes, *([stray] if stray else []), "the platform baseline is untouched", UNREACHABLE]
