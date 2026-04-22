"""Bootstrap platform tenant permissions, role, and claim mapping config.

Idempotently creates the following for the reserved 'platform' tenant:

  0. Platform org    — via porth_common OrganizationRepository (creates org + tenant together)
  1. Permissions     — via porth_common PermissionRepository
  2. platform-admin  — via porth_common RoleRepository (system role)
  3. Role–permissions — via porth_common RoleRepository.set_role_permissions
  4. Claim mapping   — via porth_common ClaimMappingConfigRepository

Step 0 must run first — the TENANT#platform DynamoDB record must exist before the
authorizer can resolve organization_id for platform admin logins.

Table names are resolved from env vars by porth_common.config:
    PORTH_TENANTS_TABLE
    PORTH_PERMISSIONS_TABLE
    PORTH_ROLES_TABLE
    PORTH_CLAIM_MAPPING_CONFIGS_TABLE

These are set in CI from the porth-components CloudFormation stack outputs.

Usage (local):
    PORTH_TENANTS_TABLE=porth-tenants-dev \\
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
from porth_common.providers.aws.repositories.organization_repo import OrganizationRepository
from porth_common.providers.aws.repositories.permission_repo import PermissionRepository
from porth_common.providers.aws.repositories.role_repo import RoleRepository
from porth_common.providers.aws.repositories.tenant_repo import TenantRepository
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


def bootstrap_platform_org_and_tenant(
    org_repo: OrganizationRepository,
    tenant_repo: TenantRepository,
) -> str:
    """Idempotently create the platform Organisation and TENANT#platform records.

    The TENANT#platform record must exist in DynamoDB before the authorizer can
    resolve organization_id for platform admin logins.  Returns the org_id.
    """
    existing = tenant_repo.get_by_id(TENANT_ID)
    if existing:
        print(f"    exists   TENANT#{TENANT_ID} (org_id={existing.org_id})")
        return existing.org_id

    org, tenant = org_repo.create_with_tenant(
        org_data={
            "name": "Platform",
            "slug": "platform",
        },
        tenant_data={
            "tenant_id": TENANT_ID,
            "display_name": "Platform",
            "environment_type": "production",
        },
    )
    print(f"    created  ORG#{org.id} + TENANT#{TENANT_ID}")
    return org.id


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


PLATFORM_ADMIN_SOURCE_KEY = "platform-admin"


def bootstrap_role(repo: RoleRepository) -> str:
    """Idempotently create (or repair) the platform-admin system role.

    Returns the role UUID.

    Also patches source_key if the existing role has the wrong value —
    the source_key must match what the Auth0 Action injects in the
    https://porth.io/roles JWT claim so claim_resolver can map it to
    the correct role ID.
    """
    existing = repo.search_roles(
        tenant_id=TENANT_ID, query="platform-admin", is_system=True
    )
    for role in existing:
        if role.name == "platform-admin":
            current_sk = getattr(role, "source_key", None)
            if current_sk != PLATFORM_ADMIN_SOURCE_KEY:
                repo.update_role_source_key(
                    TENANT_ID, role.id, PLATFORM_ADMIN_SOURCE_KEY
                )
                print(
                    f"    patched  platform-admin source_key: {current_sk!r} → {PLATFORM_ADMIN_SOURCE_KEY!r}"
                )
            else:
                print(f"    exists   platform-admin (id={role.id})")
            return role.id

    role = repo.create_role(
        tenant_id=TENANT_ID,
        name="platform-admin",
        description="System role for platform-level tenant administration",
        is_system=True,
        source_key=PLATFORM_ADMIN_SOURCE_KEY,
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
    org_repo = OrganizationRepository()
    tenant_repo = TenantRepository()
    perm_repo = PermissionRepository()
    role_repo = RoleRepository()
    config_repo = ClaimMappingConfigRepository()

    print("Bootstrapping platform tenant")

    print("\n0. Platform org + tenant")
    bootstrap_platform_org_and_tenant(org_repo, tenant_repo)
    print("   ✅ platform org and tenant ready")

    print("\n1. Permissions")
    permission_keys = bootstrap_permissions(perm_repo)
    print(f"   ✅ {len(permission_keys)} permissions ready")

    print("\n2. platform-admin role")
    role_id = bootstrap_role(role_repo)
    print(f"   ✅ role_id={role_id}")

    print("\n3. Role–permission links")
    bootstrap_role_permissions(role_repo, role_id, permission_keys)
    print("   ✅ permissions linked")

    print("\n4. Claim mapping config")
    bootstrap_claim_mapping_config(config_repo, role_id)
    print("   ✅ claim mapping config ready")

    print("\n✅ Platform tenant bootstrap complete")


if __name__ == "__main__":
    main()
