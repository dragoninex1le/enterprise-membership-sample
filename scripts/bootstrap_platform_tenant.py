"""Bootstrap platform tenant permissions, role, and claim mapping config.

Idempotently creates the following for the reserved 'platform' tenant:

  1. Permissions       — via porth_common PermissionRepository
  2. platform-admin    — via porth_common RoleRepository (system role)
  3. Role–permissions  — via porth_common RoleRepository.set_role_permissions
  4. Claim mapping     — via porth_common ClaimMappingConfigRepository

Table names are resolved from env vars by porth_common.config:
    PORTH_PERMISSIONS_TABLE
    PORTH_ROLES_TABLE
    PORTH_CLAIM_MAPPING_CONFIGS_TABLE

These are set in CI from the porth-components CloudFormation stack outputs.

Usage (local):
    PORTH_PERMISSIONS_TABLE=porth-permissions-dev \\
    PORTH_ROLES_TABLE=porth-roles-dev \\
    PORTH_CLAIM_MAPPING_CONFIGS_TABLE=porth-claim-mapping-configs-dev \\
    AWS_REGION=us-east-1 python3 scripts/bootstrap_platform_tenant.py
"""

from __future__ import annotations

import hashlib

from porth_common.providers.aws.repositories.claim_mapping_config_repo import (
    ClaimMappingConfigRepository,
)
from porth_common.providers.aws.repositories.permission_repo import PermissionRepository
from porth_common.providers.aws.repositories.role_repo import RoleRepository
from porth_common.services.claim_mapping_codegen import MappingCodegen

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TENANT_ID = "platform"
APP_NAMESPACE = "porth-platform"

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
        "icon_hint": None,
        "sort_order": 10,
    },
    {
        "key": "platform.tenants.create",
        "display_name": "Create Tenants",
        "description": "Provision new tenants on the platform",
        "category": "Tenants",
        "icon_hint": None,
        "sort_order": 20,
    },
    {
        "key": "platform.tenants.update",
        "display_name": "Update Tenants",
        "description": "Modify tenant configuration and IDP settings",
        "category": "Tenants",
        "icon_hint": None,
        "sort_order": 30,
    },
    {
        "key": "platform.tenants.delete",
        "display_name": "Delete Tenants",
        "description": "Remove tenants from the platform",
        "category": "Tenants",
        "icon_hint": None,
        "sort_order": 40,
    },
    # Organisations
    {
        "key": "platform.orgs.read",
        "display_name": "View Organisations",
        "description": "View organisation records",
        "category": "Organisations",
        "icon_hint": None,
        "sort_order": 10,
    },
    {
        "key": "platform.orgs.create",
        "display_name": "Create Organisations",
        "description": "Create new organisations",
        "category": "Organisations",
        "icon_hint": None,
        "sort_order": 20,
    },
    {
        "key": "platform.orgs.update",
        "display_name": "Update Organisations",
        "description": "Modify organisation details",
        "category": "Organisations",
        "icon_hint": None,
        "sort_order": 30,
    },
    {
        "key": "platform.orgs.delete",
        "display_name": "Delete Organisations",
        "description": "Remove organisations from the platform",
        "category": "Organisations",
        "icon_hint": None,
        "sort_order": 40,
    },
    # Settings
    {
        "key": "platform.settings.read",
        "display_name": "View Platform Settings",
        "description": "View platform-level configuration",
        "category": "Settings",
        "icon_hint": None,
        "sort_order": 10,
    },
    {
        "key": "platform.settings.write",
        "display_name": "Edit Platform Settings",
        "description": "Modify platform-level configuration",
        "category": "Settings",
        "icon_hint": None,
        "sort_order": 20,
    },
]

# Claim mapping config — maps https://porth.io/roles JWT claim to roles.
# schema_version must be '2.0' (enforced by MappingSource Pydantic model).
MAPPING_SOURCE: dict = {
    "schema_version": "2.0",
    "fields": [
        {
            "name": "roles",
            "source": "https://porth.io/roles",
            "type": "collection",
            "required": False,
            "ops": [{"op": "resolve_roles"}],
        },
    ],
    "default_roles": [],
}


# ---------------------------------------------------------------------------
# Bootstrap steps
# ---------------------------------------------------------------------------


def bootstrap_permissions(repo: PermissionRepository) -> list[str]:
    """Idempotently register all platform admin permissions."""
    permission_keys: list[str] = []
    for perm in PLATFORM_PERMISSIONS:
        repo.register(
            tenant_id=TENANT_ID,
            app_namespace=APP_NAMESPACE,
            key=perm["key"],
            display_name=perm["display_name"],
            category=perm["category"],
            description=perm["description"],
            icon_hint=perm["icon_hint"],
            sort_order=perm["sort_order"],
        )
        print(f"    registered  {perm['key']}")
        permission_keys.append(perm["key"])
    return permission_keys


def bootstrap_role(repo: RoleRepository) -> str:
    """Idempotently create the platform-admin system role.

    Returns the role UUID.
    """
    existing = repo.search_roles(
        tenant_id=TENANT_ID, query="platform-admin", is_system=True
    )
    for role in existing:
        if role.name == "platform-admin":
            print(f"    exists   platform-admin (id={role.id})")
            return role.id

    role = repo.create_role(
        tenant_id=TENANT_ID,
        name="platform-admin",
        description="System role for platform-level tenant administration",
        is_system=True,
        source_key="platform_admin",
    )
    print(f"    created  platform-admin (id={role.id})")
    return role.id


def bootstrap_role_permissions(
    repo: RoleRepository, role_id: str, permission_keys: list[str]
) -> None:
    """Replace all permissions on the platform-admin role."""
    repo.set_role_permissions(
        role_id=role_id,
        permission_keys=permission_keys,
        tenant_id=TENANT_ID,
    )
    print(f"    set {len(permission_keys)} permissions on platform-admin")


def bootstrap_claim_mapping_config(
    repo: ClaimMappingConfigRepository, role_id: str
) -> None:
    """Idempotently create/update the claim mapping config."""
    compiled_source = MappingCodegen.generate(MAPPING_SOURCE)
    compiled_hash = hashlib.sha256(compiled_source.encode()).hexdigest()

    latest = repo.get_latest(TENANT_ID)
    if latest and latest.compiled_hash == compiled_hash:
        print(f"    exists   claim mapping config v{latest.version} (no change)")
        return

    config = repo.save(
        tenant_id=TENANT_ID,
        mapping_source=MAPPING_SOURCE,
        compiled_source=compiled_source,
        compiled_hash=compiled_hash,
    )
    print(f"    saved    claim mapping config v{config.version}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
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
