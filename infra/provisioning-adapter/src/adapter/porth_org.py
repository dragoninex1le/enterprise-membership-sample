"""`porth-org` - seed and teardown. The porth-org ruling, Option A (Richard, 2026-10-23): an
organisation is its own entity, seeded before the tenants that belong to it.

**What a seeded organisation is.** Exactly the organisation half of what Porth 0.3.1 writes for
`POST /organizations/` (porth-common 0.0.9 `OrganizationRepository.create_with_tenant`): one row in
the tenants table - `PK = ENV#{s}#ORG#{uuid}`, `SK = METADATA`, the slug index
`gsi1pk = ENV#{s}#ORG_SLUG#{slug}` - with a conditional put, and the `Organization.created` event.
Porth 0.3.1 only ever creates an organisation together with its first tenant, so porth-common has no
organisation-only create to call; the row and the event are written here, field for field.

**One state Porth's API never produces:** an organisation with no tenants, between this seed and the
first `porth-tenant` seed. Porth reads it without complaint - it is an ordinary org row - and it
lasts only until a tenant is seeded into it, or this run is torn down.

**It adds organisations; it never takes one over.** A slug that already exists was not written by
this dataset and is refused. Teardown refuses to remove an organisation that still has tenants:
tear the tenants down first - which `teardown` with no entity does, tenants before organisations.
"""
from __future__ import annotations

import json
import os
import re

import datasets
import ledger
from envelope import ContractError
from porth_tenant import Porth

ENTITY = "porth-org"
TYPE = "porth.org"
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def _org(resource: object) -> dict:
    if not isinstance(resource, dict) or resource.get("type") != TYPE:
        kind = resource.get("type") if isinstance(resource, dict) else type(resource).__name__
        raise ContractError("unsupported", "not_implemented", f"resource type {kind!r} is not implemented for {ENTITY}")
    slug = resource.get("alias")
    spec = resource.get("spec") or {}
    extra = sorted(set(spec) - {"name"})
    if extra:
        raise ContractError("refused", "dataset_conflict", f"organisation {slug!r}: unknown fields {extra}")
    if not isinstance(slug, str) or not _SLUG.fullmatch(slug):
        raise ContractError("refused", "dataset_conflict", f"organisation slug {slug!r} must match {_SLUG.pattern}")
    if not isinstance(spec.get("name"), str) or not spec["name"].strip():
        raise ContractError("refused", "dataset_conflict", f"organisation {slug!r} has no name")
    return {"slug": slug, "name": spec["name"]}


def _handle(slug: str, org_id: str | None, outcome: str, run_id: str) -> dict:
    handle = {"alias": slug, "type": TYPE, "entity": ENTITY, "outcome": outcome, "labels": {"run_id": run_id}}
    if org_id:  # Porth assigns the id at write time; a dry run has none to report.
        handle["id"] = org_id
    return handle


def seed(env_scope: str, run_id: str, dry_run: bool, payload: object) -> tuple[list[dict], list[str]]:
    dataset = datasets.accept(payload)
    wanted = [_org(r) for r in dataset["resources"]]
    label = f"dataset {dataset['id']} {dataset['version']} ({dataset['digest']})"
    porth = Porth(env_scope, run_id)

    current = ledger.marker(porth.db, env_scope, ENTITY)
    if current:
        if (current["dataset_id"], current["version"], current["digest"]) == (dataset["id"], dataset["version"], dataset["digest"]):
            return [{**h, "outcome": "unchanged"} for h in json.loads(current["handles"])], [f"{label} is already applied"]
        raise ContractError(
            "refused", "dataset_conflict",
            f"{ENTITY} already carries dataset {current['dataset_id']} {current['version']} "
            f"(run {current['run_id']}); tear that run down before seeding a different one",
        )

    for o in wanted:
        if porth.orgs.get_by_slug(o["slug"]) is not None:
            raise ContractError(
                "refused", "dataset_conflict",
                f"organisation {o['slug']!r} already exists in {env_scope} and was not written by this dataset; "
                "it is never overwritten",
            )
    if dry_run:
        return [_handle(o["slug"], None, "created", run_id) for o in wanted], \
            [f"dry run: {label} would be applied; nothing written"]

    from porth_common.providers.aws.repositories.base import generate_id, utc_now
    from porth_common.models.organization import Organization

    table = os.environ["PORTH_TENANTS_TABLE"]
    handles = []
    for o in wanted:
        org_id, now = generate_id(), utc_now()
        key = {"PK": f"ENV#{env_scope}#ORG#{org_id}", "SK": "METADATA"}
        ledger.record(porth.db, env_scope, run_id, ENTITY, ledger.item(table, key))
        # create_with_tenant's org item and conditional put, field for field.
        porth.db.put_item(
            TableName=table,
            Item={
                "PK": {"S": key["PK"]}, "SK": {"S": "METADATA"},
                "gsi1pk": {"S": f"ENV#{env_scope}#ORG_SLUG#{o['slug']}"}, "gsi1sk": {"S": "METADATA"},
                "id": {"S": org_id}, "name": {"S": o["name"]}, "slug": {"S": o["slug"]},
                "status": {"S": "active"}, "created_at": {"S": now}, "updated_at": {"S": now},
            },
            ConditionExpression="attribute_not_exists(PK)",
        )
        org = Organization(id=org_id, name=o["name"], slug=o["slug"], status="active", created_at=now, updated_at=now)
        porth.publisher.publish(entity_type="Organization", action="created", entity_id=org_id,
                                after=org.model_dump(), metadata={"organization_id": org_id})
        handles.append(_handle(o["slug"], org_id, "created", run_id))

    ledger.set_marker(porth.db, env_scope, ENTITY, dataset, run_id, handles)
    return handles, [f"{label} applied"]


def teardown(env_scope: str, run_id: str, target_run: str) -> tuple[list[dict], list[str]]:
    porth = Porth(env_scope, run_id)
    writes = ledger.writes(porth.db, env_scope, target_run, ENTITY)
    if writes is None:
        return [], [f"nothing in {ENTITY} is labelled with run {target_run}"]

    orgs = [e["key"] for e in writes if e["kind"] == "item"]
    for key in orgs:
        org_id = key["PK"].split("#ORG#", 1)[1]
        if porth.tenants.list_by_org(org_id):
            raise ContractError(
                "refused", "dataset_conflict",
                f"organisation {org_id} still has tenants; tear them down first (teardown with no entity does)",
            )
    for key in reversed(orgs):
        org_id = key["PK"].split("#ORG#", 1)[1]
        porth.db.delete_item(TableName=os.environ["PORTH_TENANTS_TABLE"], Key={k: {"S": v} for k, v in key.items()})
        porth.publisher.publish(entity_type="Organization", action="deleted", entity_id=org_id,
                                metadata={"organization_id": org_id})
    ledger.forget(porth.db, env_scope, target_run, ENTITY)
    return [], [f"run {target_run}: removed {len(orgs)} organisation(s)"]
