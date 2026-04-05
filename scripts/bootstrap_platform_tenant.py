"""Bootstrap platform tenant permissions, role, and claim role mapping in DynamoDB.

Idempotently creates the following for the reserved 'platform' tenant:

  1. Permissions (porth-permissions table)
     — One permission per atomic platform admin capability

  2. platform-admin role (porth-roles table)
     — System role (undeletable), scoped to tenant_id='platform'

  3. Role–permission links (porth-roles table)
     — Associates all platform permissions to the platform-admin role

  4. Claim role mapping (porth-claim-role-mappings table)
     — Maps JWT claim https://porth.io/roles='platform_admin' to the platform-admin role

Usage:
    PORTH_ENVIRONMENT=prod AWS_REGION=us-east-1 python3 scripts/bootstrap_platform_tenant.py
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
ENVIRONMENT = os.environ.get("PORTH_ENVIRONMENT", "prod")

TENANT_ID = "platform"
APP_NAMESPACE = "porth-platform"
CLAIM_KEY = "https://porth.io/roles"
CLAIM_VALUE = "platform_admin"

PERMISSIONS_TABLE = f"porth-permissions-{ENVIRONMENT}"
ROLES_TABLE = f"porth-roles-{ENVIRONMENT}"
CLAIM_ROLE_MAPPINGS_TABLE = f"porth-claim-role-mappings-{ENVIRONMENT}"

# ---------------------------------------------------------------------------
# Platform admin permissions
# ---------------------------------------------------------------------------

PLATFORM_PERMISSIONS = [
    # Tenants
    {
        "key": "platform.tenants.read",
        "display_name": "View Tenants",
        "description": "View tenant records and configuration",
        "category": "Tenants",
        "sort_order": 10,
    },
    {
        "key": "platform.tenants.create",
        "display_name": "Create Tenants",
        "description": "Provision new tenants on the platform",
        "category": "Tenants",
        "sort_order": 20,
    },
    {
        "key": "platform.tenants.update",
        "display_name": "Update Tenants",
        "description": "Modify tenant configuration and IDP settings",
        "category": "Tenants",
        "sort_order": 30,
    },
    {
        "key": "platform.tenants.delete",
        "display_name": "Delete Tenants",
        "description": "Remove tenants from the platform",
        "category": "Tenants",
        "sort_order": 40,
    },
    # Organisations
    {
        "key": "platform.orgs.read",
        "display_name": "View Organisations",
        "description": "View organisation records",
        "category": "Organisations",
        "sort_order": 10,
    },
    {
        "key": "platform.orgs.create",
        "display_name": "Create Organisations",
        "description": "Create new organisations",
        "category": "Organisations",
        "sort_order": 20,
    },
    {
        "key": "platform.orgs.update",
        "display_name": "Update Organisations",
        "description": "Modify organisation details",
        "category": "Organisations",
        "sort_order": 30,
    },
    {
        "key": "platform.orgs.delete",
        "display_name": "Delete Organisations",
        "description": "Remove organisations from the platform",
        "category": "Organisations",
        "sort_order": 40,
    },
    # Settings
    {
        "key": "platform.settings.read",
        "display_name": "View Platform Settings",
        "description": "View platform-level configuration",
        "category": "Settings",
        "sort_order": 10,
    },
    {
        "key": "platform.settings.write",
        "display_name": "Edit Platform Settings",
        "description": "Modify platform-level configuration",
        "category": "Settings",
        "sort_order": 20,
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Bootstrap steps
# ---------------------------------------------------------------------------

def bootstrap_permissions(table) -> list[str]:
    """Idempotently register platform admin permissions.

    Returns the list of permission keys written.
    """
    now = utc_now()
    permission_keys: list[str] = []

    for perm in PLATFORM_PERMISSIONS:
        pk = f"TENANT#{TENANT_ID}#NS#{APP_NAMESPACE}"
        sk = f"PERM#{perm['key']}"

        response = table.get_item(Key={"pk": pk, "sk": sk})

        if "Item" in response:
            table.update_item(
                Key={"pk": pk, "sk": sk},
                UpdateExpression="SET display_name = :dn, sort_order = :so, updated_at = :ua",
                ExpressionAttributeValues={
                    ":dn": perm["display_name"],
                    ":so": perm["sort_order"],
                    ":ua": now,
                },
            )
            print(f"    updated  {perm['key']}")
        else:
            table.put_item(
                Item={
                    "pk": pk,
                    "sk": sk,
                    "gsi1pk": f"TENANT#{TENANT_ID}",
                    "gsi1sk": f"CAT#{perm['category']}#PERM#{perm['key']}",
                    "id": generate_id(),
                    "key": perm["key"],
                    "display_name": perm["display_name"],
                    "description": perm["description"],
                    "app_namespace": APP_NAMESPACE,
                    "tenant_id": TENANT_ID,
                    "category": perm["category"],
                    "sort_order": perm["sort_order"],
                    "created_at": now,
                    "updated_at": now,
                }
            )
            print(f"    created  {perm['key']}")

        permission_keys.append(perm["key"])

    return permission_keys


def bootstrap_role(table) -> str:
    """Idempotently create the platform-admin system role.

    Returns the role UUID (existing or newly created).
    """
    now = utc_now()
    pk = f"TENANT#{TENANT_ID}"

    response = table.query(KeyConditionExpression=Key("pk").eq(pk))
    for item in response.get("Items", []):
        if item.get("name") == "platform-admin" and item.get("is_system"):
            print(f"    exists   platform-admin (id={item['id']})")
            return item["id"]

    role_id = generate_id()
    table.put_item(
        Item={
            "pk": pk,
            "sk": f"ROLE#{role_id}",
            "id": role_id,
            "tenant_id": TENANT_ID,
            "name": "platform-admin",
            "description": "System role for platform-level tenant administration",
            "is_system": True,
            "created_at": now,
            "updated_at": now,
        }
    )
    print(f"    created  platform-admin (id={role_id})")
    return role_id


def bootstrap_role_permissions(table, role_id: str, permission_keys: list[str]) -> None:
    """Replace all permissions on the platform-admin role."""
    now = utc_now()
    pk = f"ROLE#{role_id}"

    # Remove stale permissions
    existing = table.query(KeyConditionExpression=Key("pk").eq(pk))
    for item in existing.get("Items", []):
        table.delete_item(Key={"pk": pk, "sk": item["sk"]})

    # Write current permission set
    for perm_key in permission_keys:
        table.put_item(
            Item={
                "pk": pk,
                "sk": f"PERM#{perm_key}",
                "role_id": role_id,
                "permission_key": perm_key,
                "tenant_id": TENANT_ID,
                "assigned_at": now,
            }
        )

    print(f"    set {len(permission_keys)} permissions on platform-admin")


def bootstrap_claim_mapping(table, role_id: str) -> None:
    """Idempotently create the claim role mapping for platform_admin."""
    now = utc_now()
    pk = f"TENANT#{TENANT_ID}#NS#{APP_NAMESPACE}"

    existing = table.query(KeyConditionExpression=Key("pk").eq(pk))
    for item in existing.get("Items", []):
        if (
            item.get("claim_key") == CLAIM_KEY
            and item.get("claim_value") == CLAIM_VALUE
            and item.get("role_id") == role_id
        ):
            print(f"    exists   {CLAIM_KEY} = {CLAIM_VALUE} -> platform-admin")
            return

    mapping_id = generate_id()
    table.put_item(
        Item={
            "pk": pk,
            "sk": f"MAPPING#{mapping_id}",
            "gsi1pk": f"TENANT#{TENANT_ID}",
            "gsi1sk": f"MAPPING#{mapping_id}",
            "id": mapping_id,
            "tenant_id": TENANT_ID,
            "app_namespace": APP_NAMESPACE,
            "claim_key": CLAIM_KEY,
            "claim_value": CLAIM_VALUE,
            "role_id": role_id,
            "match_type": "exact",
            "value_transform": "none",
            "priority": 100,
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }
    )
    print(f"    created  {CLAIM_KEY} = {CLAIM_VALUE} -> platform-admin")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)

    permissions_table = dynamodb.Table(PERMISSIONS_TABLE)
    roles_table = dynamodb.Table(ROLES_TABLE)
    claim_mappings_table = dynamodb.Table(CLAIM_ROLE_MAPPINGS_TABLE)

    print(f"Bootstrapping platform tenant  [environment={ENVIRONMENT}]")

    print("\n1. Permissions")
    permission_keys = bootstrap_permissions(permissions_table)
    print(f"   ✅ {len(permission_keys)} permissions ready")

    print("\n2. platform-admin role")
    role_id = bootstrap_role(roles_table)
    print(f"   ✅ role_id={role_id}")

    print("\n3. Role–permission links")
    bootstrap_role_permissions(roles_table, role_id, permission_keys)
    print("   ✅ permissions linked")

    print("\n4. Claim role mapping")
    bootstrap_claim_mapping(claim_mappings_table, role_id)
    print("   ✅ claim mapping ready")

    print("\n✅ Platform tenant bootstrap complete")


if __name__ == "__main__":
    main()
