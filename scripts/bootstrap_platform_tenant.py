"""Bootstrap platform tenant permissions, role, and claim mapping config.

Idempotently creates the following for the reserved 'platform' tenant using
direct DynamoDB calls (no porth-common dependency):

  0. Platform org + tenant items in the tenants table
  1. Platform-admin permissions
  2. platform-admin system role (with source_key)
  3. Role–permission links
  4. Claim mapping config (compiled_source pre-generated, no codegen needed)

Direct DynamoDB writes are required because the Porth API itself calls
assert_active(tenant_id) which requires TENANT#platform to already exist —
bootstrapping via the API would be circular.

ADR-Z8 environment scoping (PORTH-532)
--------------------------------------
When ``PORTH_ENV_SCOPE`` is set, every **partition** key is written as
``ENV#{scope}#…``. This must match the Porth install's ``FixedEnvironment``
(single-env) or the target slot (multi-env): an authorizer pinned to ``prod``
resolves ``ENV#prod#TENANT#platform`` and simply will not see an unscoped record
(PORTH-514 — the failure is silent, the tenant just appears not to exist).

Leaving it unset preserves the previous unscoped behaviour byte-for-byte.

Table names are resolved from env vars:
    PORTH_TENANTS_TABLE
    PORTH_PERMISSIONS_TABLE
    PORTH_ROLES_TABLE
    PORTH_CLAIM_MAPPING_CONFIGS_TABLE
    PORTH_ENV_SCOPE   (optional; e.g. "prod")

Usage (local):
    PORTH_TENANTS_TABLE=porth-tenants-dev \\
    PORTH_PERMISSIONS_TABLE=porth-permissions-dev \\
    PORTH_ROLES_TABLE=porth-roles-dev \\
    PORTH_CLAIM_MAPPING_CONFIGS_TABLE=porth-claim-mapping-configs-dev \\
    PORTH_ENV_SCOPE=prod \\
    AWS_REGION=us-east-1 python3 scripts/bootstrap_platform_tenant.py
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REGION = os.environ.get("AWS_REGION", "us-east-1")
APP_NS = "porth-platform"

# ADR-Z8 data axis. Distinct from the table-name suffix (dev/staging) — conflating
# the two writes records the authorizer never looks for.
ENV_SCOPE = os.environ.get("PORTH_ENV_SCOPE", "").strip()

PERMISSIONS = [
    {"key": "platform.tenants.read",   "display_name": "View Tenants",           "category": "Tenants",       "sort_order": 10},
    {"key": "platform.tenants.create", "display_name": "Create Tenants",          "category": "Tenants",       "sort_order": 20},
    {"key": "platform.tenants.update", "display_name": "Update Tenants",          "category": "Tenants",       "sort_order": 30},
    {"key": "platform.tenants.delete", "display_name": "Delete Tenants",          "category": "Tenants",       "sort_order": 40},
    {"key": "platform.orgs.read",      "display_name": "View Organisations",      "category": "Organisations", "sort_order": 10},
    {"key": "platform.orgs.create",    "display_name": "Create Organisations",    "category": "Organisations", "sort_order": 20},
    {"key": "platform.orgs.update",    "display_name": "Update Organisations",    "category": "Organisations", "sort_order": 30},
    {"key": "platform.orgs.delete",    "display_name": "Delete Organisations",    "category": "Organisations", "sort_order": 40},
    {"key": "platform.settings.read",  "display_name": "View Platform Settings",  "category": "Settings",      "sort_order": 10},
    {"key": "platform.settings.write", "display_name": "Edit Platform Settings",  "category": "Settings",      "sort_order": 20},
]

# The roles-claim namespace is derived from the Auth0 API identifier (the audience),
# because that is what the post-login Action namespaces its custom claims with. The two
# MUST agree: the mapping matches the claim key character-for-character, so a namespace
# that doesn't match the audience means the claim is never found, roles resolve empty,
# and the admin gets no menu — with nothing in the logs saying why (PORTH-479).
#
# It was previously hardcoded to "https://porth.io/roles", which is not this install's
# audience. Style Classifier uses "https://porth.elegans-dev.estynsoftware.io/roles",
# matching ITS audience — the value is per-install, so it cannot be a constant.
def _roles_namespace() -> str:
    explicit = os.environ.get("PORTH_ROLES_NAMESPACE", "").strip()
    if explicit:
        return explicit

    audience = os.environ.get("PORTH_AUTH_AUDIENCE", "").strip()
    if not audience:
        # Read it from the same blob the proxy and authorizer use, so there is one
        # source of truth rather than a second value to keep in step.
        blob = boto3.client("ssm", region_name=REGION).get_parameter(
            Name="/porth/auth", WithDecryption=True
        )["Parameter"]["Value"]
        audience = (json.loads(blob).get("audience") or "").strip()

    if not audience:
        raise SystemExit(
            "Cannot derive the roles-claim namespace: no audience in /porth/auth and "
            "neither PORTH_AUTH_AUDIENCE nor PORTH_ROLES_NAMESPACE is set. Refusing to "
            "write a claim mapping that would silently resolve no roles."
        )
    return f"{audience.rstrip('/')}/roles"


ROLES_NAMESPACE = _roles_namespace()

MAPPING_SOURCE = {
    "schema_version": "2.0",
    "fields": [
        {
            "name": "roles",
            "source": ROLES_NAMESPACE,
            "type": "collection",
            "required": False,
            "ops": [{"op": "resolve_roles"}],
        }
    ],
    "default_roles": [],
}

# compiled_source pre-generated by MappingCodegen.generate(MAPPING_SOURCE)
# Re-generate locally if the mapping schema changes:
#   from porth_common.services.claim_mapping_codegen import MappingCodegen
#   print(MappingCodegen.generate(MAPPING_SOURCE))
COMPILED_SOURCE = (
    "# AUTO-GENERATED by claim_mapping_codegen — config hash c9845fb83254fbc8\n"
    "# DO NOT EDIT manually. Re-generate from the mapping config.\n"
    "from __future__ import annotations\n"
    "from typing import Any\n"
    "from porth_common.services.exceptions import MappingError\n"
    "\n"
    "def _get_path(obj: dict, path: str) -> Any:\n"
    '    """OIDC-aware dot-notation path resolver."""\n'
    "    if not isinstance(obj, dict) or not path:\n"
    "        return None\n"
    '    if path.startswith(("http://", "https://")):\n'
    "        return obj.get(path)\n"
    '    parts = path.split(".")\n'
    "    current: Any = obj\n"
    "    for part in parts:\n"
    "        if not isinstance(current, dict):\n"
    "            return None\n"
    "        current = current.get(part)\n"
    "        if current is None:\n"
    "            return None\n"
    "    return current\n"
    "\n"
    "def map_claims(claims: dict, role_registry: dict | None = None) -> dict:\n"
    '    """Map JWT claims to user model fields.\n'
    "    \n"
    "    Args:\n"
    "        claims: Raw JWT claims dict from identity provider.\n"
    "        role_registry: Optional dict mapping source_key values to role IDs.\n"
    "            Required for fields with resolve_roles op.\n"
    "    Returns:\n"
    "        Dict of {field_name: transformed_value}.\n"
    "    Raises:\n"
    "        MappingError: If a required claim is absent.\n"
    '    """\n'
    "    result: dict = {}\n"
    "\n"
    "    # field: roles (collection)\n"
    f"    _v = claims.get('{ROLES_NAMESPACE}')\n"
    "    if _v is not None:\n"
    "        if not isinstance(_v, list):\n"
    "            _v = [_v]\n"
    "        _collection = []\n"
    "        for _elem in _v:\n"
    "            _ev = _elem\n"
    "            # resolve_roles: match against role registry\n"
    "            if _ev is not None and role_registry is not None:\n"
    "                _ev = role_registry.get(str(_ev))\n"
    "            if _ev is not None:\n"
    "                _collection.append(_ev)\n"
    "        result['roles'] = list(dict.fromkeys(_collection))\n"
    "\n"
    "    return result\n"
)
COMPILED_HASH = "55016a468cbb18927879e32725927fc3d501a7887918f05eed50911918fd6855"


# ---------------------------------------------------------------------------
# ADR-Z8 key scoping
# ---------------------------------------------------------------------------

def env_key(base: str) -> str:
    """Apply the ADR-Z8 environment prefix to a *partition* key string.

    Mirrors ``porth_common.providers.aws.repositories.base._env_key``: the environment is
    folded into the **content** of the partition key attribute (``PK``/``pk`` and
    ``gsiNpk``) — never the table ``KeySchema`` — so it triggers no table replace.

    Apply only to partition (hash) keys, never sort keys: environment is an outer
    partition axis, so prefixing a sort key would be wrong.

    Returns ``base`` unchanged when no scope is bound, preserving single-env behaviour.
    """
    return f"ENV#{ENV_SCOPE}#{base}" if ENV_SCOPE else base


# ---------------------------------------------------------------------------
# Bootstrap helpers
# ---------------------------------------------------------------------------

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def bootstrap_platform_org_and_tenant(tenants_tbl, now: str) -> str:
    platform_pk = env_key("TENANT#platform")
    existing = tenants_tbl.get_item(Key={"PK": platform_pk, "SK": "METADATA"})
    if "Item" in existing:
        org_id = existing["Item"]["org_id"]
        print(f"    exists   {platform_pk} (org_id={org_id})")
        return org_id

    org_id = str(uuid.uuid4())
    tenants_tbl.put_item(Item={
        "PK": env_key(f"ORG#{org_id}"), "SK": "METADATA",
        "gsi1pk": env_key("ORG_SLUG#platform"), "gsi1sk": "METADATA",
        "id": org_id, "name": "Platform", "slug": "platform",
        "status": "active", "created_at": now, "updated_at": now,
    })
    tenants_tbl.put_item(Item={
        "PK": platform_pk, "SK": "METADATA",
        "gsi1pk": env_key(f"ORG#{org_id}"), "gsi1sk": "TENANT#platform",
        "tenant_id": "platform", "org_id": org_id, "org_name": "Platform",
        # PORTH-502: environment_type was renamed tenant_tier.
        "display_name": "Platform", "tenant_tier": "production",
        "status": "active", "created_at": now, "updated_at": now,
    })
    print(f"    created  {env_key(f'ORG#{org_id}')} + {platform_pk}")
    return org_id


def bootstrap_permissions(perms_tbl, now: str) -> list[str]:
    permission_keys: list[str] = []
    for p in PERMISSIONS:
        perms_tbl.put_item(Item={
            "pk": env_key(f"TENANT#platform#NS#{APP_NS}"), "sk": f"PERM#{p['key']}",
            "gsi1pk": env_key("TENANT#platform"), "gsi1sk": f"CAT#{p['category']}#PERM#{p['key']}",
            "id": str(uuid.uuid4()), "key": p["key"], "display_name": p["display_name"],
            "category": p["category"], "app_namespace": APP_NS,
            "tenant_id": "platform", "sort_order": p["sort_order"],
            "created_at": now, "updated_at": now,
        })
        permission_keys.append(p["key"])
        print(f"    registered  {p['key']}")
    return permission_keys


def bootstrap_role(roles_tbl, now: str) -> str:
    platform_pk = env_key("TENANT#platform")
    resp = roles_tbl.query(
        KeyConditionExpression=Key("pk").eq(platform_pk) & Key("sk").begins_with("ROLE#")
    )
    for item in resp.get("Items", []):
        if item.get("name") == "platform-admin":
            role_id = item["id"]
            if item.get("source_key") != "platform-admin":
                roles_tbl.update_item(
                    Key={"pk": platform_pk, "sk": f"ROLE#{role_id}"},
                    UpdateExpression="SET source_key = :sk, updated_at = :ua",
                    ExpressionAttributeValues={":sk": "platform-admin", ":ua": now},
                )
                print(f"    patched  source_key → platform-admin (id={role_id})")
            else:
                print(f"    exists   platform-admin (id={role_id})")
            return role_id

    role_id = str(uuid.uuid4())
    roles_tbl.put_item(Item={
        "pk": platform_pk, "sk": f"ROLE#{role_id}",
        "id": role_id, "tenant_id": "platform", "name": "platform-admin",
        "is_system": True, "source_key": "platform-admin",
        "description": "System role for platform-level tenant administration",
        "created_at": now, "updated_at": now,
    })
    print(f"    created  platform-admin (id={role_id})")
    return role_id


def bootstrap_role_permissions(roles_tbl, role_id: str, permission_keys: list[str], now: str) -> None:
    role_pk = env_key(f"ROLE#{role_id}")
    # Remove old links
    old = roles_tbl.query(
        KeyConditionExpression=Key("pk").eq(role_pk) & Key("sk").begins_with("PERM#")
    )
    for item in old.get("Items", []):
        roles_tbl.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})

    # Write new links
    for pkey in permission_keys:
        roles_tbl.put_item(Item={
            "pk": role_pk, "sk": f"PERM#{pkey}",
            "role_id": role_id, "permission_key": pkey,
            "tenant_id": "platform", "assigned_at": now,
        })
    print(f"    set {len(permission_keys)} permissions on platform-admin")


def bootstrap_claim_mapping_config(claim_tbl, now: str) -> None:
    platform_pk = env_key("TENANT#platform")
    existing_cfg = claim_tbl.query(
        KeyConditionExpression=Key("PK").eq(platform_pk),
        ScanIndexForward=False,
        Limit=1,
    )
    if existing_cfg.get("Items"):
        latest = existing_cfg["Items"][0]
        if latest.get("compiled_hash") == COMPILED_HASH:
            print(f"    exists   claim mapping config v{latest['version']} (no change)")
            return
        version = latest["version"] + 1
    else:
        version = 1

    claim_tbl.put_item(Item={
        "PK": platform_pk, "SK": f"VERSION#{version:06d}",
        "gsi1pk": platform_pk, "gsi1sk": f"VERSION#{version:06d}",
        "id": str(uuid.uuid4()), "tenant_id": "platform", "version": version,
        "mapping_source": MAPPING_SOURCE, "compiled_source": COMPILED_SOURCE,
        "compiled_hash": COMPILED_HASH,
        "compiled_at": now, "created_at": now, "updated_at": now,
    })
    print(f"    saved    claim mapping config v{version}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    dynamodb = boto3.resource("dynamodb", region_name=REGION)

    tenants_tbl = dynamodb.Table(os.environ["PORTH_TENANTS_TABLE"])
    perms_tbl   = dynamodb.Table(os.environ["PORTH_PERMISSIONS_TABLE"])
    roles_tbl   = dynamodb.Table(os.environ["PORTH_ROLES_TABLE"])
    claim_tbl   = dynamodb.Table(os.environ["PORTH_CLAIM_MAPPING_CONFIGS_TABLE"])

    now = utc_now()

    if ENV_SCOPE:
        print(f"Bootstrapping platform tenant (ADR-Z8 scope: ENV#{ENV_SCOPE}#…)")
    else:
        print("Bootstrapping platform tenant (unscoped — PORTH_ENV_SCOPE not set)")

    print("\n0. Platform org + tenant")
    bootstrap_platform_org_and_tenant(tenants_tbl, now)
    print("   ✅ platform org and tenant ready")

    print("\n1. Permissions")
    permission_keys = bootstrap_permissions(perms_tbl, now)
    print(f"   ✅ {len(permission_keys)} permissions ready")

    print("\n2. platform-admin role")
    role_id = bootstrap_role(roles_tbl, now)
    print(f"   ✅ role_id={role_id}")

    print("\n3. Role–permission links")
    bootstrap_role_permissions(roles_tbl, role_id, permission_keys, now)
    print("   ✅ permissions linked")

    print("\n4. Claim mapping config")
    bootstrap_claim_mapping_config(claim_tbl, now)
    print("   ✅ claim mapping config ready")

    print("\n✅ Platform tenant bootstrap complete")


if __name__ == "__main__":
    main()
