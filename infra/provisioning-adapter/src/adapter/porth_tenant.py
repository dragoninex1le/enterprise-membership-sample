"""`porth-tenant` - seed (PRF-12) and teardown (PRF-15).

**What a seeded tenant is.** What Porth writes when a tenant is added to an existing organisation
(`PUT /tenants/`), using Porth's own code for every write (porth-common 0.0.21, Porth 0.4.10):

1. the tenant row, through porth-common's `TenantRepository.create` - PK/SK, both indexes (gsi2 is
   what lists it), and the `Tenant.created` and `tenant.created` events;
2. the tenant-admin role and its grants, through porth-common's `ensure_tenant_admin_role` - the one
   function Porth's API and porth-install both provision a tenant admin with (PORTH-643). The API's
   two configuration values are passed as their defaults (role name `tenant-admin`, no platform
   overrides). The grants include `tenant.claim_mappings.manage`, without which Porth refuses a
   tenant its own claim mapping (PORTH-637/638).

3. the tenant's IdP config (`idp_config_override`), when the dataset carries one - through
   porth-common's `TenantRepository.update`, validated by Porth 0.3.1's `TenantPatch`. It lives on the
   tenant row and is part of the tenant (Richard, 2026-10-25). Porth 0.3.1's `PUT /tenants/` accepts
   it but porth-common 0.0.9's `create` drops it, so in 0.3.1 it is set by `PATCH /tenants/{id}` -
   which is `update`, and what this does.

Nothing else: no claim mapping (`porth-claim-mapping`, its own table and entity - one call, one
entity, D12) and nothing in the identity provider. porth-common is pinned to the release the Porth
EMS runs shipped; when a Porth change affects what a seed writes, the pin moves with it.

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
ATTRIBUTES = {"tenant_tier", "org", "admin_role_source_key", "idp_config_override"}


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
        from porth_common.providers.aws.repositories.claim_mapping_config_repo import ClaimMappingConfigRepository
        from porth_common.providers.aws.repositories.organization_repo import OrganizationRepository
        from porth_common.providers.aws.repositories.permission_repo import PermissionRepository
        from porth_common.providers.aws.repositories.role_repo import RoleRepository
        from porth_common.providers.aws.repositories.tenant_repo import TenantRepository
        from porth_common.providers.aws.events.publisher import EventPublisher

        # Porth's audit trail names who acted and in which slot; this run is the actor.
        set_audit_context(actor_id=f"prawf:{run_id}", environment=env_scope)
        self.publisher = EventPublisher(client=self.events, environment=env_scope)
        # porth-common 0.0.21 (PORTH-632): a repository takes a callable that returns the resource and
        # resolves it per access. One resource, already holding this run's session credentials.
        def connect():
            return resource
        self.orgs = OrganizationRepository(tenants, connect, event_publisher=self.publisher, environment=env_scope)
        self.tenants = TenantRepository(tenants, connect, event_publisher=self.publisher, environment=env_scope)
        self.claims = ClaimMappingConfigRepository(os.environ["PORTH_CLAIM_MAPPING_CONFIGS_TABLE"], connect,
                                                   event_publisher=self.publisher, environment=env_scope)
        self.roles = RoleRepository(roles, connect, events_client=self.events, environment=env_scope)
        self.permissions = PermissionRepository(permissions, connect, events_client=self.events, environment=env_scope)


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
            f"tenant {tenant_id!r}: attributes {extra} are not part of a Porth tenant "
            f"(it takes {', '.join(sorted(ATTRIBUTES))}), and nothing here writes to the identity provider",
        )
    from pydantic import ValidationError
    from porth_common.models.tenant import TenantAddToOrg, TenantIdpConfig

    idp = attributes.get("idp_config_override")
    if isinstance(idp, dict):
        # Porth's model ignores a field it does not define - it would be dropped without a word, and the
        # tenant would quietly differ from its dataset. Refused instead, by name.
        dropped = sorted(set(idp) - set(TenantIdpConfig.model_fields))
        if dropped:
            raise ContractError(
                "refused", "dataset_conflict",
                f"tenant {tenant_id!r}: idp_config_override fields {dropped} are not ones Porth 0.3.1 keeps "
                f"(it keeps {', '.join(sorted(TenantIdpConfig.model_fields))})",
            )

    try:
        TenantAddToOrg(
            org_id="validated-separately",
            tenant_id=tenant_id,
            display_name=spec.get("display_name"),
            tenant_tier=attributes.get("tenant_tier"),
            admin_role_source_key=attributes.get("admin_role_source_key"),
            idp_config_override=attributes.get("idp_config_override"),
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
        "idp_config_override": attributes.get("idp_config_override"),
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
    from porth_common.tenants.admin_role import ensure_tenant_admin_role

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
        if t["idp_config_override"]:
            # PATCH /tenants/{id}, Porth 0.3.1: TenantPatch's dump, without unset fields, through update.
            from porth_common.models.tenant import TenantPatch
            porth.tenants.update(tid, TenantPatch(idp_config_override=t["idp_config_override"]).model_dump(exclude_none=True))

        # The tenant-admin role, the one way Porth provisions it (porth-common 0.0.21, PORTH-643): the
        # API's PUT /tenants/ and porth-install both call this. Porth's own tenant permissions come from
        # its static catalogue - tenant.claim_mappings.manage among them - plus what applications
        # registered in the environment's catalogue. The API's two configuration values are passed as
        # their defaults: role name `tenant-admin`, no platform overrides.
        ledger.record(porth.db, env_scope, run_id, ENTITY, ledger.tenant_scope(tid))
        ensure_tenant_admin_role(role_repo=porth.roles, permission_repo=porth.permissions,
                                 tenant_id=tid, source_key=t["admin_role_source_key"])
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


def _query_all(porth: Porth, table: str, pk_attr: str, value: str, index: str | None = None) -> list[dict]:
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


def users_of(porth: Porth, env_scope: str, tenant_id: str) -> list[dict]:
    return _query_all(porth, os.environ["PORTH_USERS_TABLE"], "gsi3pk", f"ENV#{env_scope}#TENANT#{tenant_id}", index="gsi3")


def org_units_of(porth: Porth, env_scope: str, tenant_id: str) -> list[dict]:
    return _query_all(porth, os.environ["PORTH_ORG_UNITS_TABLE"], "PK", f"ENV#{env_scope}#TENANT#{tenant_id}")


def _sweep_tenant(porth: Porth, env_scope: str, tenant_id: str) -> None:
    """Every row keyed under a tenant: its roles, grants and permissions, its users with their role
    assignments, and its org units. Nothing is left pointing at a tenant that has gone."""
    _, roles_table, permissions_table = _tables()
    base = f"ENV#{env_scope}#TENANT#{tenant_id}"

    def query(table: str, pk_attr: str, value: str, index: str | None = None) -> list[dict]:
        return _query_all(porth, table, pk_attr, value, index)

    for user in users_of(porth, env_scope, tenant_id):
        user_id = user["id"]["S"]
        for assignment in query(roles_table, "pk", f"{base}#USER#{user_id}"):
            porth.db.delete_item(TableName=roles_table, Key={"pk": assignment["pk"], "sk": assignment["sk"]})
        porth.db.delete_item(TableName=os.environ["PORTH_USERS_TABLE"], Key={"PK": user["PK"], "SK": user["SK"]})
        porth.publisher.publish(entity_type="User", action="deleted", entity_id=user_id, metadata={"tenant_id": tenant_id})
    for unit in org_units_of(porth, env_scope, tenant_id):
        porth.db.delete_item(TableName=os.environ["PORTH_ORG_UNITS_TABLE"], Key={"PK": unit["PK"], "SK": unit["SK"]})

    for role in query(roles_table, "pk", base):
        if not role["sk"]["S"].startswith("ROLE#"):
            continue
        role_id = role["sk"]["S"].removeprefix("ROLE#")
        for grant in query(roles_table, "pk", f"{base}#ROLE#{role_id}"):
            porth.db.delete_item(TableName=roles_table, Key={"pk": grant["pk"], "sk": grant["sk"]})
        porth.db.delete_item(TableName=roles_table, Key={"pk": role["pk"], "sk": role["sk"]})
    for permission in query(permissions_table, "gsi1pk", base, index="gsi1"):
        porth.db.delete_item(TableName=permissions_table, Key={"pk": permission["pk"], "sk": permission["sk"]})
