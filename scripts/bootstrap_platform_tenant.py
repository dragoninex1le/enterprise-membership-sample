"""Bootstrap platform tenant permissions, role, and claim mapping config in DynamoDB.

Idempotently creates the following for the reserved 'platform' tenant:

  1. Permissions (porth-permissions-{env} table)
     — One permission per atomic platform admin capability

  2. platform-admin role (porth-roles-{env} table)
     — System role (undeletable), scoped to tenant_id='platform'

  3. Role–permission links (porth-roles-{env} table)
     — Associates all platform permissions to the platform-admin role

  4. Claim mapping config v2 (porth-claim-mapping-configs-{env} table)
     — Maps JWT claim https://porth.io/roles='platform_admin' to the
       platform-admin role via a versioned ClaimMappingConfig entry.
       A new version is only written when the compiled_hash changes.

Table names are resolved via porth_common.config (PORTH_PERMISSIONS_TABLE,
PORTH_ROLES_TABLE, PORTH_CLAIM_MAPPING_CONFIGS_TABLE env vars), which are
set from the porth-components CloudFormation stack outputs in CI.

Usage:
    PORTH_PERMISSIONS_TABLE=porth-permissions-dev \\
    PORTH_ROLES_TABLE=porth-roles-dev \\
    PORTH_CLAIM_MAPPING_CONFIGS_TABLE=porth-claim-mapping-configs-dev \\
    python3 scripts/bootstrap_platform_tenant.py
"""

from __future__ import annotations

import hashlib
import json

from porth_common.providers.aws.repositories.permission_repo import PermissionRepository
from porth_common.providers.aws.repositories.role_repo import RoleRepository
from porth_common.providers.aws.repositories.claim_mapping_config_repo import ClaimMappingConfigRepository
from porth_common.services.claim_mapping_codegen import MappingCodegen

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TENANT_ID = "platform"
APP_NAMESPACE = "porth-platform"
CLAIM_KEY = "https://porth.io/roles"
CLAIM_VALUE = "platform_admin"

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
# Bootstrap steps
# ---------------------------------------------------------------------------

def bootstrap_permissions(repo: PermissionRepository) -> list[str]:
    """Idempotently register platform admin permissions via PermissionRepository."""
    permission_keys: list[str] = []
    for perm in PLATFORM_PERMISSIONS:
        repo.register(
            tenant_id=TENANT_ID,
            app_namespace=APP_NAMESPACE,
            key=perm["key"],
            display_name=perm["display_name"],
            category=perm["category"],
            description=perm.get("description"),
            sort_order=perm.get("sort_order", 0),
        )
        print(f"    registered  {perm['key']}")
        permission_keys.append(perm["key"])
    return permission_keys


def bootstrap_role(repo: RoleRepository) -> str:
    """Idempotently create the platform-admin system role.

    Returns the role ID (existing or newly created).
    """
    existing = [
        r for r in repo.search_roles(TENANT_ID, is_system=True)
        if r and r.name == "platform-admin"
    ]
    if existing:
        role = existing[0]
        print(f"    exists   platform-admin (id={role.id})")
        return role.id

    role = repo.create_role(
        tenant_id=TENANT_ID,
        name="platform-admin",
        description="System role for platform-level tenant administration",
        is_system=True,
    )
    print(f"    created  platform-admin (id={role.id})")
    return role.id


def bootstrap_role_permissions(
    repo: RoleRepository, role_id: str, permission_keys: list[str]
) -> None:
    """Replace all permissions on the platform-admin role."""
    repo.set_role_permissions(role_id, permission_keys, TENANT_ID)
    print(f"    set {len(permission_keys)} permissions on platform-admin")


def bootstrap_claim_mapping_config(
    repo: ClaimMappingConfigRepository, role_id: str
) -> None:
    """Idempotently save a v2 ClaimMappingConfig for the platform claim-to-role mapping.

    A new version is only written when the compiled_hash differs from the latest,
    avoiding unnecessary version churn on repeated deploys.
    """
    mapping_source = {
        "version": 2,
        "fields": [],
        "role_mappings": [
            {
                "claim_key": CLAIM_KEY,
                "claim_value": CLAIM_VALUE,
                "role_id": role_id,
                "match_type": "exact",
                "priority": 100,
                "value_transform": "none",
            }
        ],
        "default_roles": [],
    }

    compiled_source = MappingCodegen.generate(mapping_source)
    compiled_hash = hashlib.sha256(compiled_source.encode()).hexdigest()

    latest = repo.get_latest(TENANT_ID)
    if latest and latest.compiled_hash == compiled_hash:
        print(f"    exists   claim mapping config v{latest.version} (no change)")
        return

    config = repo.save(
        tenant_id=TENANT_ID,
        mapping_source=mapping_source,
        compiled_source=compiled_source,
        compiled_hash=compiled_hash,
    )
    print(f"    saved    claim mapping config v{config.version}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    # Table names resolved from porth_common.config via env vars set by CI
    perm_repo = PermissionRepository()
    role_repo = RoleRepository()
    config_repo = ClaimMappingConfigRepository()

    print("Bootstrapping platform tenant")

    print("\n1. Permissions")
    permission_keys = bootstrap_permissions(perm_repo)
    print(f"   \u2705 {len(permission_keys)} permissions ready")

    print("\n2. platform-admin role")
    role_id = bootstrap_role(role_repo)
    print(f"   \u2705 role_id={role_id}")

    print("\n3. Role\u2013permission links")
    bootstrap_role_permissions(role_repo, role_id, permission_keys)
    print("   \u2705 permissions linked")

    print("\n4. Claim mapping config")
    bootstrap_claim_mapping_config(config_repo, role_id)
    print("   \u2705 claim mapping config ready")

    print("\n\u2705 Platform tenant bootstrap complete")


if __name__ == "__main__":
    main()
