"""`porth-tenant` - seed (PRF-12) and teardown (PRF-15).

**What a seeded tenant is.** Exactly what Porth 0.3.1 - the version EMS runs - writes when a tenant
is added to an existing organisation (`PUT /tenants/`), using Porth's own code for every write:

1. the tenant row, through porth-common's `TenantRepository.create` - PK/SK, both indexes (gsi2 is
   what lists it), and the `Tenant.created` and `tenant.created` events;
2. the tenant-admin role, the tenant-namespace permissions registered under the tenant, and the
   role's grants - through porth-common's `RoleRepository` and `PermissionRepository`. Porth 0.3.1
   orchestrated these three calls in its API service (`provision_tenant_admin_role`), which is not
   in the wheel; the orchestration below is that function's, step for step, with the two
   configuration values it read passed as their defaults (role name `tenant-admin`, no platform
   overrides).

Nothing else: no IdP config (`porth-idp-config`) and no claim mapping (`porth-claim-mapping`) - one
call, one entity (D12) - and nothing in the identity provider. porth-common is pinned to 0.0.9, the
release SAR 0.3.1 shipped; when EMS moves to a newer Porth, the pin moves with it.

**It adds tenants; it never takes one over.** The organisation must already exist - Porth 0.3.1 had
no way to create one alone - and the tenant must not. An existing tenant was not written by this
dataset, and overwriting it would destroy someone else's state, so it is refused, not adopted.

**One bad row stops every login in the slot** (Porth's tenant directory loads them all), so each
resource is validated with Porth 0.3.1's own request model before anything is written.
"""
from __future__ import annotations

import os

import aws
import datasets
import ledger
import slots
from envelope import ContractError

ENTITY = "porth-tenant"
ADMIN_ROLE_NAME = "tenant-admin"
ADMIN_ROLE_DESCRIPTION = "Tenant Administrator — full access to all tenant-level features"
PLATFORM_NAMESPACE = "porth-platform"
ATTRIBUTES = {"tenant_tier", "org", "admin_role_source_key"}


def _tables() -> tuple[str, str, str]:
    return os.environ["PORTH_TENANTS_TABLE"], os.environ["PORTH_ROLES_TABLE"], os.environ["PORTH_PERMISSIONS_TABLE"]


class Porth:
    """porth-common's repositories, bound to one slot, on the one-slot session's credentials."""

    def __init__(self, env_scope: str, run_id: str):
        creds = slots.data_credentials(env_scope)
        self.db = aws.client("dynamodb", **creds)
        self.events = aws.client("events", **creds)
        resource = aws.resource("dynamodb", **creds)
        tenants, roles, permissions = _tables()

        # The repositories package first: importing the publisher module first is a circular import.
        from porth_common.audit.context import set_audit_context
        from porth_common.providers.aws.repositories.organization_repo import OrganizationRepository
        from porth_common.providers.aws.repositories.permission_repo import PermissionRepository
        from porth_common.providers.aws.repositories.role_repo import RoleRepository
        from porth_common.providers.aws.repositories.tenant_repo import TenantRepository
        from porth_common.providers.aws.events.publisher import EventPublisher

        # Porth's audit trail names who acted and in which slot; this run is the actor.
        set_audit_context(actor_id=f"prawf:{run_id}", environment=env_scope)
        self.publisher = EventPublisher(client=self.events, environment=env_scope)
        self.orgs = OrganizationRepository(tenants, resource, event_publisher=self.publisher, environment=env_scope)
        self.tenants = TenantRepository(tenants, resource, event_publisher=self.publisher, environment=env_scope)
        self.roles = RoleRepository(roles, resource, events_client=self.events, environment=env_scope)
        self.permissions = PermissionRepository(permissions, resource, events_client=self.events, environment=env_scope)


def _tenant(resource: object) -> dict:
    """One dataset resource as Porth 0.3.1's `PUT /tenants/` request, validated by Porth's own model."""
    if not isinstance(resource, dict) or resource.get("type") != "tenant":
        kind = resource.get("type") if isinstance(resource, dict) else type(resource).__name__
        raise ContractError("unsupported", "not_implemented", f"resource type {kind!r} is not implemented for {ENTITY}")
    tenant_id = resource.get("alias")
    spec = resource.get("spec") or {}
    attributes = spec.get("attributes") or {}
    extra = sorted(set(attributes) - ATTRIBUTES)
    if extra:
        raise ContractError(
            "refused", "dataset_conflict",
            f"tenant {tenant_id!r}: attributes {extra} are not part of {ENTITY} - IdP settings belong to "
            "porth-idp-config, and nothing here writes to the identity provider",
        )
    from pydantic import ValidationError
    from porth_common.models.tenant import TenantAddToOrg

    try:
        TenantAddToOrg(
            org_id="validated-separately",
            tenant_id=tenant_id,
            display_name=spec.get("display_name"),
            tenant_tier=attributes.get("tenant_tier"),
            admin_role_source_key=attributes.get("admin_role_source_key"),
        )
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors())
        raise ContractError("refused", "dataset_conflict", f"tenant {tenant_id!r} is not valid for Porth: {problems}") from e
    if not isinstance(attributes.get("org"), str) or not attributes["org"]:
        raise ContractError("refused", "dataset_conflict", f"tenant {tenant_id!r} names no org (its slug)")
    return {
        "tenant_id": tenant_id,
        "display_name": spec["display_name"],
        "tenant_tier": attributes["tenant_tier"],
        "org": attributes["org"],
        "admin_role_source_key": attributes["admin_role_source_key"],
    }


def _handle(tenant_id: str, outcome: str, run_id: str) -> dict:
    return {"alias": tenant_id, "type": "tenant", "entity": ENTITY, "id": tenant_id,
            "outcome": outcome, "labels": {"run_id": run_id}}


def seed(env_scope: str, run_id: str, dry_run: bool, payload: object) -> tuple[list[dict], list[str]]:
    dataset = datasets.accept(payload)
    wanted = [_tenant(r) for r in dataset["resources"]]
    label = f"dataset {dataset['id']} {dataset['version']} ({dataset['digest']})"
    porth = Porth(env_scope, run_id)

    # §8.4: the same dataset again converges; a different one is refused until the entity is reset.
    current = ledger.marker(porth.db, env_scope, ENTITY)
    if current:
        if (current["dataset_id"], current["version"], current["digest"]) == (dataset["id"], dataset["version"], dataset["digest"]):
            return [_handle(t["tenant_id"], "unchanged", current["run_id"]) for t in wanted], [f"{label} is already applied"]
        raise ContractError(
            "refused", "dataset_conflict",
            f"{ENTITY} already carries dataset {current['dataset_id']} {current['version']} "
            f"(run {current['run_id']}); tear that run down before seeding a different one",
        )

    orgs = {}
    for t in wanted:
        org = porth.orgs.get_by_slug(t["org"])
        if org is None:
            raise ContractError(
                "refused", "dataset_conflict",
                f"tenant {t['tenant_id']!r} names org {t['org']!r}, which does not exist in {env_scope}",
            )
        orgs[t["tenant_id"]] = org
        if porth.tenants.get_by_id(t["tenant_id"]) is not None:
            raise ContractError(
                "refused", "dataset_conflict",
                f"tenant {t['tenant_id']!r} already exists in {env_scope} and was not written by this dataset; "
                "it is never overwritten",
            )

    if dry_run:
        return [_handle(t["tenant_id"], "created", run_id) for t in wanted], [f"dry run: {label} would be applied; nothing written"]

    tenants_table, _, _ = _tables()
    from porth_common.permissions import catalogue

    handles = []
    for t in wanted:
        tid, org = t["tenant_id"], orgs[t["tenant_id"]]
        ledger.record(porth.db, env_scope, run_id, ENTITY, ledger.item(
            tenants_table, {"PK": f"ENV#{env_scope}#TENANT#{tid}", "SK": "METADATA"}))
        porth.tenants.create({
            "tenant_id": tid, "org_id": org.id, "org_name": org.name,
            "display_name": t["display_name"], "tenant_tier": t["tenant_tier"],
            "created_by": f"prawf:{run_id}",
        })

        # provision_tenant_admin_role, Porth 0.3.1 - role, then the tenant permissions, then grants.
        ledger.record(porth.db, env_scope, run_id, ENTITY, ledger.tenant_scope(tid))
        role = porth.roles.create_role(
            tenant_id=tid, name=ADMIN_ROLE_NAME, source_key=t["admin_role_source_key"],
            is_system=True, description=ADMIN_ROLE_DESCRIPTION,
        )
        for spec in catalogue.CATALOGUE:
            if spec.namespace == PLATFORM_NAMESPACE:
                continue
            porth.permissions.register(
                tenant_id=tid, app_namespace=spec.namespace, key=spec.id, display_name=spec.display_name,
                description=spec.description, category=spec.category, sort_order=spec.sort_order,
            )
        keys = sorted({p.key for p in porth.permissions.list_by_tenant(tid) if p.app_namespace != PLATFORM_NAMESPACE})
        if keys:
            porth.roles.set_role_permissions(role.id, keys, tid)
        handles.append(_handle(tid, "created", run_id))

    ledger.set_marker(porth.db, env_scope, ENTITY, dataset, run_id, handles)
    return handles, [f"{label} applied"]


def teardown(env_scope: str, run_id: str, target_run: str) -> tuple[list[dict], list[str]]:
    """Remove everything `target_run` wrote to this entity. Idempotent: nothing left is `ok`, quietly."""
    porth = Porth(env_scope, run_id)
    writes = ledger.writes(porth.db, env_scope, target_run, ENTITY)
    if writes is None:
        return [], [f"nothing in {ENTITY} is labelled with run {target_run}"]

    removed = []
    for entry in reversed(writes):
        if entry["kind"] == "tenant":
            _sweep_tenant(porth, env_scope, entry["tenant_id"])
        else:
            key = entry["key"]
            porth.db.delete_item(TableName=entry["table"], Key={k: {"S": v} for k, v in key.items()})
            if key.get("SK") == "METADATA" and "#TENANT#" in key.get("PK", ""):
                # The tenant row itself. Porth 0.3.1 has no hard delete to call, so the row goes
                # directly - and the events its consumers would expect go with it.
                tid = key["PK"].split("#TENANT#", 1)[1]
                porth.publisher.publish(entity_type="Tenant", action="deleted", entity_id=tid,
                                        metadata={"tenant_id": tid})
                porth.publisher.publish_tenant_lifecycle(action="deleted", tenant_id=tid)
                removed.append(tid)
    ledger.forget(porth.db, env_scope, target_run, ENTITY)
    return [], [f"run {target_run}: removed tenant(s) {', '.join(removed) or '(none left)'} and everything under them"]


def _sweep_tenant(porth: Porth, env_scope: str, tenant_id: str) -> None:
    """Every role, grant and permission row under a tenant this run created."""
    _, roles_table, permissions_table = _tables()
    base = f"ENV#{env_scope}#TENANT#{tenant_id}"

    def query(table: str, pk_attr: str, value: str, index: str | None = None) -> list[dict]:
        kwargs = {"TableName": table, "KeyConditionExpression": f"{pk_attr} = :v",
                  "ExpressionAttributeValues": {":v": {"S": value}}}
        if index:
            kwargs["IndexName"] = index
        items, start = [], None
        while True:
            if start:
                kwargs["ExclusiveStartKey"] = start
            page = porth.db.query(**kwargs)
            items += page.get("Items", [])
            start = page.get("LastEvaluatedKey")
            if not start:
                return items

    for role in query(roles_table, "pk", base):
        if not role["sk"]["S"].startswith("ROLE#"):
            continue
        role_id = role["sk"]["S"].removeprefix("ROLE#")
        for grant in query(roles_table, "pk", f"{base}#ROLE#{role_id}"):
            porth.db.delete_item(TableName=roles_table, Key={"pk": grant["pk"], "sk": grant["sk"]})
        porth.db.delete_item(TableName=roles_table, Key={"pk": role["pk"], "sk": role["sk"]})
    for permission in query(permissions_table, "gsi1pk", base, index="gsi1"):
        porth.db.delete_item(TableName=permissions_table, Key={"pk": permission["pk"], "sk": permission["sk"]})
