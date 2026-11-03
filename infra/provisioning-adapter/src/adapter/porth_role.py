"""`porth-role` - seed (PRF-18) and teardown; reset is reset.py's.

**What a seeded role is.** An arranged role - one a test needs that the tenant's seed does not make,
such as a role with no grants for a denial test (`porth-role:no-access`). Exactly what Porth 0.3.1
writes for `POST /roles/`: `RoleRepository.create_role` with `is_system=False`, which is never taken
from the caller (PORTH-597) - so a seeded role is always one reset may remove, and never one that
locks a tenant out of its own administration. No grants are written: a role is arranged with the
permissions a test gives it, and the denial test gives it none.

The tenant must exist (seed `porth-tenant` first), and the role's name and claim value must be free in
it - Porth refuses a duplicate (PORTH-226), and so does this.
"""
from __future__ import annotations

import datasets
import ledger
from envelope import ContractError
from porth_tenant import Porth

ENTITY = "porth-role"
TYPE = "porth.role"


def _role(resource: object) -> dict:
    if not isinstance(resource, dict) or resource.get("type") != TYPE:
        kind = resource.get("type") if isinstance(resource, dict) else type(resource).__name__
        raise ContractError("unsupported", "not_implemented", f"resource type {kind!r} is not implemented for {ENTITY}")
    name = resource.get("alias")
    spec = resource.get("spec") or {}
    extra = sorted(set(spec) - {"tenant", "source_key", "description"})
    if extra:
        raise ContractError("refused", "dataset_conflict", f"role {name!r}: unknown fields {extra} - a seeded role has no grants")
    for field, value in (("alias (the role's name)", name), ("spec.tenant", spec.get("tenant")),
                         ("spec.source_key", spec.get("source_key"))):
        if not isinstance(value, str) or not value.strip():
            raise ContractError("refused", "dataset_conflict", f"role {name!r} has no {field}")
    return {"name": name, "tenant_id": spec["tenant"], "source_key": spec["source_key"],
            "description": spec.get("description") or ""}


def _handle(r: dict, role_id: str | None, outcome: str, run_id: str) -> dict:
    handle = {"alias": r["name"], "type": TYPE, "entity": ENTITY, "outcome": outcome, "labels": {"run_id": run_id}}
    if role_id:
        handle["id"] = role_id
    return handle


def seed(env_scope: str, run_id: str, dry_run: bool, payload: object) -> tuple[list[dict], list[str]]:
    dataset = datasets.accept(payload)
    wanted = [_role(r) for r in dataset["resources"]]
    label = f"dataset {dataset['id']} {dataset['version']} ({dataset['digest']})"
    porth = Porth(env_scope, run_id)

    current = ledger.marker(porth.db, env_scope, ENTITY)
    if current:
        if (current["dataset_id"], current["version"], current["digest"]) == (dataset["id"], dataset["version"], dataset["digest"]):
            return [_handle(r, None, "unchanged", current["run_id"]) for r in wanted], [f"{label} is already applied"]
        raise ContractError(
            "refused", "dataset_conflict",
            f"{ENTITY} already carries dataset {current['dataset_id']} {current['version']} "
            f"(run {current['run_id']}); tear that run down before seeding a different one",
        )

    for r in wanted:
        if porth.tenants.get_by_id(r["tenant_id"]) is None:
            raise ContractError(
                "refused", "dataset_conflict",
                f"role {r['name']!r} names tenant {r['tenant_id']!r}, which does not exist in {env_scope}; seed porth-tenant first",
            )
        taken = [x for x in porth.roles.list_roles(r["tenant_id"]) if x.name == r["name"] or x.source_key == r["source_key"]]
        if taken:
            raise ContractError(
                "refused", "dataset_conflict",
                f"tenant {r['tenant_id']!r} already has a role named {r['name']!r} or answering to "
                f"{r['source_key']!r}, not written by this dataset; it is never taken over",
            )
    if dry_run:
        return [_handle(r, None, "created", run_id) for r in wanted], [f"dry run: {label} would be applied; nothing written"]

    handles = []
    for r in wanted:
        # Porth assigns the id, so the ledger names the role by tenant and name - unique in a tenant.
        ledger.record(porth.db, env_scope, run_id, ENTITY, {"kind": "role", "tenant_id": r["tenant_id"], "name": r["name"]})
        role = porth.roles.create_role(tenant_id=r["tenant_id"], name=r["name"], description=r["description"],
                                       is_system=False, source_key=r["source_key"])
        handles.append(_handle(r, role.id, "created", run_id))

    ledger.set_marker(porth.db, env_scope, ENTITY, dataset, run_id, handles)
    return handles, [f"{label} applied"]


def teardown(env_scope: str, run_id: str, target_run: str) -> tuple[list[dict], list[str]]:
    porth = Porth(env_scope, run_id)
    writes = ledger.writes(porth.db, env_scope, target_run, ENTITY)
    if writes is None:
        return [], [f"nothing in {ENTITY} is labelled with run {target_run}"]
    removed = []
    for entry in reversed(writes):
        for role in porth.roles.list_roles(entry["tenant_id"]):
            if role.name == entry["name"] and not role.is_system:
                porth.roles.delete_role(entry["tenant_id"], role.id)
                removed.append(f"{entry['tenant_id']}/{role.name}")
    ledger.forget(porth.db, env_scope, target_run, ENTITY)
    return [], [f"run {target_run}: removed role(s) {', '.join(removed) or '(none left)'}"]
