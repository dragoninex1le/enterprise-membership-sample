"""`porth-claim-mapping` - seed (PRF-13), and teardown. Reset is reset.py's.

**What a seeded claim mapping is.** Exactly what Porth 0.3.1 writes for
`POST /claim-mapping-configs/?tenant_id=…`, using Porth's own code: the dataset's `mapping_source` is
validated by Porth's `MappingSource`, compiled by porth-common's `compile_mapping_source`, and saved
as the tenant's next version by `ClaimMappingConfigRepository.save`, which publishes
`ClaimMappingConfig.created`.

**Why it matters.** The authorizer resolves a signed-in user's Porth roles by running the tenant's
compiled mapping. A tenant without one signs in with no roles - "roles will be empty", the PORTH-479
trap - so a tenant seeded without its claim mapping is a broken tenant.

**The mapping is prawf's to define** (D7) and travels in the dataset; the adapter compiles it. The
tenant must already exist (seed `porth-tenant` first), and must have no claim mapping of its own -
one this dataset did not write is never added to, so it is refused, not adopted.
"""
from __future__ import annotations

import os

import datasets
import ledger
from envelope import ContractError
from porth_tenant import Porth

ENTITY = "porth-claim-mapping"
TYPE = "porth.claim-mapping"


def _mapping(resource: object) -> dict:
    if not isinstance(resource, dict) or resource.get("type") != TYPE:
        kind = resource.get("type") if isinstance(resource, dict) else type(resource).__name__
        raise ContractError("unsupported", "not_implemented", f"resource type {kind!r} is not implemented for {ENTITY}")
    tenant_id = resource.get("alias")
    spec = resource.get("spec") or {}
    extra = sorted(set(spec) - {"mapping_source"})
    if extra:
        raise ContractError("refused", "dataset_conflict", f"claim mapping for {tenant_id!r}: unknown fields {extra}")
    if not isinstance(tenant_id, str) or not tenant_id:
        raise ContractError("refused", "dataset_conflict", "a claim mapping names its tenant as its alias")
    from porth_common.services.claim_mapping_compilation_service import compile_mapping_source
    from porth_common.services.exceptions import CompilationError

    try:
        compiled = compile_mapping_source(mapping_source=spec.get("mapping_source") or {})
    except CompilationError as e:
        raise ContractError("refused", "dataset_conflict", f"claim mapping for {tenant_id!r} does not compile: {e}") from e
    return {"tenant_id": tenant_id, "mapping_source": spec["mapping_source"], "compiled": compiled}


def _handle(tenant_id: str, config_id: str | None, outcome: str, run_id: str) -> dict:
    handle = {"alias": tenant_id, "type": TYPE, "entity": ENTITY, "outcome": outcome, "labels": {"run_id": run_id}}
    if config_id:
        handle["id"] = config_id
    return handle


def _versions(porth: Porth, env_scope: str, tenant_id: str) -> list[dict]:
    return porth.db.query(
        TableName=os.environ["PORTH_CLAIM_MAPPING_CONFIGS_TABLE"],
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": {"S": f"ENV#{env_scope}#TENANT#{tenant_id}"}},
        ConsistentRead=True,
    ).get("Items", [])


def seed(env_scope: str, run_id: str, dry_run: bool, payload: object) -> tuple[list[dict], list[str]]:
    dataset = datasets.accept(payload)
    wanted = [_mapping(r) for r in dataset["resources"]]
    label = f"dataset {dataset['id']} {dataset['version']} ({dataset['digest']})"
    porth = Porth(env_scope, run_id)

    current = ledger.marker(porth.db, env_scope, ENTITY)
    if current:
        if (current["dataset_id"], current["version"], current["digest"]) == (dataset["id"], dataset["version"], dataset["digest"]):
            return [_handle(m["tenant_id"], None, "unchanged", current["run_id"]) for m in wanted], [f"{label} is already applied"]
        raise ContractError(
            "refused", "dataset_conflict",
            f"{ENTITY} already carries dataset {current['dataset_id']} {current['version']} "
            f"(run {current['run_id']}); tear that run down before seeding a different one",
        )

    for m in wanted:
        if porth.tenants.get_by_id(m["tenant_id"]) is None:
            raise ContractError(
                "refused", "dataset_conflict",
                f"claim mapping names tenant {m['tenant_id']!r}, which does not exist in {env_scope}; seed porth-tenant first",
            )
        if _versions(porth, env_scope, m["tenant_id"]):
            raise ContractError(
                "refused", "dataset_conflict",
                f"tenant {m['tenant_id']!r} already has a claim mapping in {env_scope}, not written by this dataset; "
                "it is never added to",
            )
    if dry_run:
        return [_handle(m["tenant_id"], None, "created", run_id) for m in wanted], \
            [f"dry run: {label} would be applied; nothing written"]

    handles = []
    for m in wanted:
        # The version Porth assigns is not known in advance, so the ledger names the tenant's lineage:
        # every version under a tenant that had none before this run.
        ledger.record(porth.db, env_scope, run_id, ENTITY, {"kind": "claims", "tenant_id": m["tenant_id"]})
        config = porth.claims.save(
            tenant_id=m["tenant_id"],
            mapping_source=m["mapping_source"],
            compiled_source=m["compiled"].compiled_source,
            compiled_hash=m["compiled"].compiled_hash,
            validation_report=m["compiled"].validation_report,
        )
        handles.append(_handle(m["tenant_id"], config.id, "created", run_id))

    ledger.set_marker(porth.db, env_scope, ENTITY, dataset, run_id, handles)
    return handles, [f"{label} applied"]


def teardown(env_scope: str, run_id: str, target_run: str) -> tuple[list[dict], list[str]]:
    porth = Porth(env_scope, run_id)
    writes = ledger.writes(porth.db, env_scope, target_run, ENTITY)
    if writes is None:
        return [], [f"nothing in {ENTITY} is labelled with run {target_run}"]
    table = os.environ["PORTH_CLAIM_MAPPING_CONFIGS_TABLE"]
    removed = []
    for entry in reversed(writes):
        for row in _versions(porth, env_scope, entry["tenant_id"]):
            porth.db.delete_item(TableName=table, Key={"PK": row["PK"], "SK": row["SK"]})
        removed.append(entry["tenant_id"])
    ledger.forget(porth.db, env_scope, target_run, ENTITY)
    return [], [f"run {target_run}: removed the claim mapping of {', '.join(removed) or '(none left)'}"]
