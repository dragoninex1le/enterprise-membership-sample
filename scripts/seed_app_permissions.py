"""Register the sample app's own permissions and grant them to tenant admins.

PORTH-610. These belong to the APP, not to Porth. Porth owns the
``porth-platform`` and ``porth-tenant`` namespaces and seeds those from its own
install; anything a consuming app enforces is the app's to register, from the
app's own deploy. That boundary is what this script exists to make real —
before it, the app's permissions were only ever created by hand, so a Porth
install that removed them (PORTH-609) left nothing to put them back.

The keys are the ones the app actually enforces. They are read from the routers'
``require_permission(...)`` calls, not from a list maintained in parallel:

    dashboard.read          routers/dashboard.py
    ar.invoices.read        routers/ar.py
    ar.invoices.write       routers/ar.py
    ap.bills.read           routers/ap.py
    ap.bills.write          routers/ap.py
    approvals.read          routers/approvals.py
    approvals.write         routers/approvals.py

Converging, like every other install step: it registers what is missing, grants
what is missing, and writes nothing on a second run.

**It only ever adds.** A permission the app no longer ships is reported and left
alone, and grants are unioned rather than replaced — the mistake PORTH-609 was
about, and the reason the app's own permissions vanished in the first place.

Environment:
    PORTH_PERMISSIONS_TABLE   e.g. porth-permissions-dev
    PORTH_ROLES_TABLE         e.g. porth-roles-dev
    PORTH_TENANTS_TABLE       e.g. porth-tenants-dev
    PORTH_ENV_SCOPE           ADR-Z8 slot, e.g. prod
    APP_TENANTS               optional: comma-separated tenant ids.
                              Omitted, every tenant in the table is seeded.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

#: The app's namespace. Porth subtracts its OWN namespaces when it computes a
#: tenant admin's grant, so anything registered here is picked up as the
#: tenant's own capability rather than a platform one.
APP_NS = "sample-app"

#: The role that gets them. Tenant capabilities belong to the tenant's
#: administrator, not the platform operator — a platform operator administering
#: another tenant's features is the thing the split exists to prevent.
TENANT_ADMIN_ROLE = "tenant-admin"

PERMISSIONS = [
    {"key": "dashboard.read",    "display_name": "View Dashboard",      "category": "Dashboard",           "sort_order": 10},
    {"key": "ar.invoices.read",  "display_name": "View Invoices",       "category": "Accounts Receivable", "sort_order": 10},
    {"key": "ar.invoices.write", "display_name": "Create/Edit Invoices", "category": "Accounts Receivable", "sort_order": 20},
    {"key": "ap.bills.read",     "display_name": "View Bills",          "category": "Accounts Payable",    "sort_order": 10},
    {"key": "ap.bills.write",    "display_name": "Create/Edit Bills",   "category": "Accounts Payable",    "sort_order": 20},
    {"key": "approvals.read",    "display_name": "View Approvals",      "category": "Approvals",           "sort_order": 10},
    {"key": "approvals.write",   "display_name": "Approve/Reject",      "category": "Approvals",           "sort_order": 20},
]

ENV_SCOPE = os.environ.get("PORTH_ENV_SCOPE", "").strip()


def env_key(base: str) -> str:
    """ADR-Z8 prefix. Matches BaseRepository._env_key exactly."""
    return f"ENV#{ENV_SCOPE}#{base}" if ENV_SCOPE else base


def tenant_key(tenant_id: str, base: str = "") -> str:
    """The tenant-leading partition key (PORTH-604).

    dynamodb:LeadingKeys binds to the START of the partition key, so every key
    this script writes has to lead with the tenant — a row filed the old way is
    invisible to the repositories that now read the new shape.
    """
    suffix = f"#{base}" if base else ""
    return env_key(f"TENANT#{tenant_id}{suffix}")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def discover_tenants(tenants_tbl) -> list[str]:
    """Every tenant in this slot, from the env-scoped index."""
    resp = tenants_tbl.query(
        IndexName="gsi2",
        KeyConditionExpression=Key("gsi2pk").eq(env_key("TENANTS")),
    )
    return [i["tenant_id"] for i in resp.get("Items", []) if i.get("tenant_id")]


def register_permissions(perms_tbl, tenant_id: str, now: str) -> list[str]:
    """Create the app's permission records for *tenant_id*. Returns every key."""
    pk = tenant_key(tenant_id, f"NS#{APP_NS}")
    existing = {
        i["sk"].removeprefix("PERM#")
        for i in perms_tbl.query(KeyConditionExpression=Key("pk").eq(pk)).get("Items", [])
    }

    created = 0
    for p in PERMISSIONS:
        if p["key"] in existing:
            continue
        perms_tbl.put_item(Item={
            "pk": pk,
            "sk": f"PERM#{p['key']}",
            "gsi1pk": tenant_key(tenant_id),
            "gsi1sk": f"CAT#{p['category']}#PERM#{p['key']}",
            "id": str(uuid.uuid4()),
            "key": p["key"],
            "display_name": p["display_name"],
            "category": p["category"],
            "app_namespace": APP_NS,
            "tenant_id": tenant_id,
            "sort_order": p["sort_order"],
            "created_at": now,
            "updated_at": now,
        })
        created += 1

    print(f"    permissions: {created} registered, {len(PERMISSIONS) - created} already present")
    return [p["key"] for p in PERMISSIONS]


def find_tenant_admin(roles_tbl, tenant_id: str) -> str | None:
    """The tenant's admin role id, matched by NAME.

    Reported as absent rather than guessed. Inventing an administrator for a
    tenant nobody asked us to administer is the worse failure — the same reason
    porth_common's reconciler matches on name and not on is_system.
    """
    resp = roles_tbl.query(
        KeyConditionExpression=Key("pk").eq(tenant_key(tenant_id)) & Key("sk").begins_with("ROLE#")
    )
    for item in resp.get("Items", []):
        if item.get("name") == TENANT_ADMIN_ROLE:
            return item.get("id") or item["sk"].removeprefix("ROLE#")
    return None


def grant(roles_tbl, tenant_id: str, role_id: str, keys: list[str], now: str) -> int:
    """Union the app's permissions onto the role. Never replaces.

    PORTH-609: a whole-set replace here is what silently revoked these very
    permissions. Anything already granted stays granted, whoever put it there.
    """
    pk = tenant_key(tenant_id, f"ROLE#{role_id}")
    held = {
        i["sk"].removeprefix("PERM#")
        for i in roles_tbl.query(KeyConditionExpression=Key("pk").eq(pk)).get("Items", [])
    }

    added = 0
    for key in keys:
        if key in held:
            continue
        roles_tbl.put_item(Item={
            "pk": pk,
            "sk": f"PERM#{key}",
            "role_id": role_id,
            "permission_key": key,
            "tenant_id": tenant_id,
            "assigned_at": now,
        })
        added += 1

    print(f"    grants: {added} added to {TENANT_ADMIN_ROLE}, {len(keys) - added} already held")
    return added


def main() -> int:
    perms_table = os.environ.get("PORTH_PERMISSIONS_TABLE", "").strip()
    roles_table = os.environ.get("PORTH_ROLES_TABLE", "").strip()
    tenants_table = os.environ.get("PORTH_TENANTS_TABLE", "").strip()

    missing = [n for n, v in (
        ("PORTH_PERMISSIONS_TABLE", perms_table),
        ("PORTH_ROLES_TABLE", roles_table),
        ("PORTH_TENANTS_TABLE", tenants_table),
    ) if not v]
    if missing:
        print(f"error: {', '.join(missing)} not set", file=sys.stderr)
        return 1

    ddb = boto3.resource("dynamodb")
    perms_tbl = ddb.Table(perms_table)
    roles_tbl = ddb.Table(roles_table)
    tenants_tbl = ddb.Table(tenants_table)

    explicit = os.environ.get("APP_TENANTS", "").strip()
    tenants = (
        [t.strip() for t in explicit.split(",") if t.strip()]
        if explicit
        else discover_tenants(tenants_tbl)
    )
    if not tenants:
        # Not an error: a fresh install has no tenants yet, and this step runs on
        # every deploy. Loud enough to notice, quiet enough not to fail a deploy.
        print("::warning::no tenants found — nothing to seed. If this install has "
              "tenants, check PORTH_ENV_SCOPE and that backfill-tenant-index has run.")
        return 0

    print(f"seeding {APP_NS} permissions under ENV#{ENV_SCOPE or '(none)'}#")
    now = now_iso()
    incomplete = []

    for tenant_id in tenants:
        print(f"  tenant {tenant_id}")
        keys = register_permissions(perms_tbl, tenant_id, now)

        role_id = find_tenant_admin(roles_tbl, tenant_id)
        if not role_id:
            # The permissions still exist and can be granted by hand or by a
            # later run; only the grant is missing, and saying which is the
            # difference between a five-minute fix and an afternoon.
            print(f"    ::warning::no '{TENANT_ADMIN_ROLE}' role — permissions "
                  f"registered but not granted")
            incomplete.append(tenant_id)
            continue

        grant(roles_tbl, tenant_id, role_id, keys, now)

    if incomplete:
        print(f"\n{len(incomplete)} tenant(s) have the permissions but no "
              f"{TENANT_ADMIN_ROLE} role to grant them to: {', '.join(incomplete)}")
    print("\ndone")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
