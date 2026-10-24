#!/usr/bin/env python3
"""Check, in EMS's own tables, that a seeded tenant and its organisation are in place (step 3, part 5).

Read-only. Run locally with credentials for the EMS account after prawf has seeded:

    python3 infra/provisioning-adapter/scripts/verify_seed.py --profile ems --tenant ems-test --org ems

Optionally compare against the datasets that were seeded, read from prawf's bucket:

    ... --components-profile components --version 1.0.0

What it checks, each as its own line:
  * the organisation row exists under its slug, active, with the name the dataset gave it
  * the tenant row exists as Porth 0.3.1 writes it - both indexes (gsi2 is what lists it), active,
    belonging to that organisation by id and name, with the dataset's display name and tier
  * the tenant-admin role exists, answers to the dataset's claim value, is a system role, and holds
    exactly the tenant permissions registered under the tenant
  * the adapter's dataset markers say which dataset version (and digest) each entity carries
  * **every row Porth's tenant directory loads is one Porth can read** - the directory reads them all
    (`SK = METADATA AND contains(PK, "TENANT#")`), and a single row it cannot read empties it and stops
    every login in the slot. This is the check that says the seed broke nothing around it.

Exit status 0 only when every check passes.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

PORTH_STACK = "serverlessrepo-porth-components"
TIERS = re.compile(r"^(production|staging|development|sandbox)$")
STATUSES = re.compile(r"^(active|suspended|decommissioning|deleted)$")
ROLE_TYPE = re.compile(r"^[a-z0-9-]{1,32}$")


def plain(value: dict):
    """DynamoDB JSON to Python."""
    (kind, v), = value.items()
    if kind in ("S", "N", "BOOL"):
        return v
    if kind == "NULL":
        return None
    if kind == "L":
        return [plain(x) for x in v]
    if kind == "M":
        return {k: plain(x) for k, x in v.items()}
    return v


def item(raw: dict) -> dict:
    return {k: plain(v) for k, v in raw.items()}


# ------------------------------------------------------------------ checks (pure, tested offline)

def check_org(org: dict | None, slug: str, expected_name: str | None) -> list[str]:
    if org is None:
        return [f"no organisation with slug {slug!r}"]
    problems = []
    if org.get("status") != "active":
        problems.append(f"organisation {slug!r} is {org.get('status')!r}, not active")
    if expected_name is not None and org.get("name") != expected_name:
        problems.append(f"organisation {slug!r} is named {org.get('name')!r}, the dataset says {expected_name!r}")
    return problems


def check_tenant(tenant: dict | None, slot: str, tenant_id: str, org: dict | None, expected: dict | None) -> list[str]:
    if tenant is None:
        return [f"no tenant row ENV#{slot}#TENANT#{tenant_id}"]
    problems = readable(tenant)
    if tenant.get("gsi2pk") != f"ENV#{slot}#TENANTS" or tenant.get("gsi2sk") != f"TENANT#{tenant_id}":
        problems.append("the tenant has no gsi2 keys - Porth's tenant list (GET /tenants/) will not show it")
    if tenant.get("status") != "active":
        problems.append(f"the tenant is {tenant.get('status')!r}, not active")
    if org is not None:
        if tenant.get("org_id") != org.get("id"):
            problems.append(f"the tenant's org_id {tenant.get('org_id')!r} is not organisation {org.get('slug')!r} ({org.get('id')})")
        if tenant.get("gsi1pk") != f"ENV#{slot}#ORG#{org.get('id')}":
            problems.append("the tenant is not indexed under its organisation (gsi1)")
        if tenant.get("org_name") != org.get("name"):
            problems.append(f"org_name {tenant.get('org_name')!r} differs from the organisation's {org.get('name')!r}")
    if expected:
        for field in ("display_name", "tenant_tier"):
            if tenant.get(field) != expected[field]:
                problems.append(f"{field} is {tenant.get(field)!r}, the dataset says {expected[field]!r}")
    return problems


def readable(row: dict) -> list[str]:
    """What Porth 0.3.1's Tenant model would reject on read (porth-common 0.0.9 `_item_to_tenant`)."""
    who = row.get("tenant_id") or row.get("PK")
    problems = [f"{who}: missing {f}" for f in ("tenant_id", "org_id", "display_name", "created_at", "updated_at")
                if not row.get(f)]
    if not TIERS.fullmatch(str(row.get("tenant_tier", ""))):
        problems.append(f"{who}: tenant_tier {row.get('tenant_tier')!r} is not one Porth reads")
    if not STATUSES.fullmatch(str(row.get("status", ""))):
        problems.append(f"{who}: status {row.get('status')!r} is not one Porth reads")
    if row.get("role_type") is not None and not ROLE_TYPE.fullmatch(str(row["role_type"])):
        problems.append(f"{who}: role_type {row.get('role_type')!r} is not one Porth reads")
    return problems


def check_admin_role(roles: list[dict], grants: list[str], registered: list[str], source_key: str | None) -> list[str]:
    admins = [r for r in roles if r.get("name") == "tenant-admin"]
    if len(admins) != 1:
        return [f"expected one tenant-admin role, found {len(admins)}"]
    (role,) = admins
    problems = []
    if source_key is not None and role.get("source_key") != source_key:
        problems.append(f"tenant-admin answers to {role.get('source_key')!r}, the dataset says {source_key!r}")
    if role.get("is_system") is not True:
        problems.append("tenant-admin is not a system role - the role API could delete or re-permission it")
    if not registered:
        problems.append("no tenant permissions are registered under the tenant")
    if sorted(grants) != sorted(registered):
        problems.append(f"tenant-admin holds {sorted(grants)}, but the tenant's permissions are {sorted(registered)}")
    return problems


def check_directory(rows: list[dict]) -> list[str]:
    return [p for row in rows for p in readable(row)]


# ------------------------------------------------------------------ AWS (the aws CLI, like permutations.py)

class Ems:
    def __init__(self, profile: str, region: str):
        self.base = ["aws", "--profile", profile, "--region", region, "--output", "json"]

    def call(self, *args: str) -> dict:
        proc = subprocess.run([*self.base, *args], capture_output=True, text=True)
        if proc.returncode != 0:
            sys.exit(f"aws {' '.join(args[:2])} failed: {proc.stderr.strip()}")
        return json.loads(proc.stdout or "{}")

    def outputs(self) -> dict:
        stack = self.call("cloudformation", "describe-stacks", "--stack-name", PORTH_STACK)["Stacks"][0]
        return {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}

    def get(self, table: str, key: dict) -> dict | None:
        out = self.call("dynamodb", "get-item", "--table-name", table, "--consistent-read",
                        "--key", json.dumps({k: {"S": v} for k, v in key.items()}))
        return item(out["Item"]) if "Item" in out else None

    def query(self, table: str, attr: str, value: str, index: str | None = None) -> list[dict]:
        args = ["dynamodb", "query", "--table-name", table, "--key-condition-expression", f"{attr} = :v",
                "--expression-attribute-values", json.dumps({":v": {"S": value}})]
        if index:
            args += ["--index-name", index]
        return [item(i) for i in self.call(*args).get("Items", [])]

    def directory(self, table: str) -> list[dict]:
        """The exact rows Porth's tenant directory loads."""
        out = self.call("dynamodb", "scan", "--table-name", table,
                        "--filter-expression", "SK = :m AND contains(PK, :t)",
                        "--expression-attribute-values", json.dumps({":m": {"S": "METADATA"}, ":t": {"S": "TENANT#"}}))
        return [item(i) for i in out.get("Items", [])]


def expected_from_bucket(profile: str, tenant_id: str, slug: str, version: str) -> tuple[dict, dict]:
    def fetch(key: str) -> dict:
        account = json.loads(subprocess.run(["aws", "--profile", profile, "sts", "get-caller-identity"],
                                            capture_output=True, text=True, check=True).stdout)["Account"]
        proc = subprocess.run(["aws", "--profile", profile, "s3", "cp", f"s3://prawf-datasets-{account}/{key}", "-"],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            sys.exit(f"could not read dataset {key}: {proc.stderr.strip()}")
        return json.loads(proc.stdout)
    org = fetch(f"ems/porth-org/ems.org.{slug}@{version}.json")["resources"][0]
    tenant = fetch(f"ems/porth-tenant/ems.tenant.{tenant_id}@{version}.json")["resources"][0]
    return org, tenant


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--profile", required=True, help="AWS profile for the EMS account")
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--slot", default="porth-dau")
    ap.add_argument("--tenant", default="ems-test")
    ap.add_argument("--org", default="ems", help="the organisation's slug")
    ap.add_argument("--components-profile", help="also compare against the seeded datasets in prawf's bucket")
    ap.add_argument("--version", default="1.0.0")
    args = ap.parse_args()

    ems = Ems(args.profile, args.region)
    tables = ems.outputs()
    tenants, roles_t, perms_t = tables["TenantsTableName"], tables["RolesTableName"], tables["PermissionsTableName"]
    s = args.slot

    org_expected = tenant_expected = None
    if args.components_profile:
        org_res, tenant_res = expected_from_bucket(args.components_profile, args.tenant, args.org, args.version)
        org_expected = org_res["spec"]["name"]
        attrs = tenant_res["spec"]["attributes"]
        tenant_expected = {"display_name": tenant_res["spec"]["display_name"], "tenant_tier": attrs["tenant_tier"],
                           "admin_role_source_key": attrs["admin_role_source_key"]}

    orgs = ems.query(tenants, "gsi1pk", f"ENV#{s}#ORG_SLUG#{args.org}", index="gsi1")
    org = orgs[0] if orgs else None
    tenant = ems.get(tenants, {"PK": f"ENV#{s}#TENANT#{args.tenant}", "SK": "METADATA"})
    roles = [r for r in ems.query(roles_t, "pk", f"ENV#{s}#TENANT#{args.tenant}") if str(r.get("sk", "")).startswith("ROLE#")]
    admin = next((r for r in roles if r.get("name") == "tenant-admin"), None)
    grants = [g["permission_key"] for g in ems.query(roles_t, "pk", f"ENV#{s}#TENANT#{args.tenant}#ROLE#{admin['id']}")] if admin else []
    registered = [p["key"] for p in ems.query(perms_t, "gsi1pk", f"ENV#{s}#TENANT#{args.tenant}", index="gsi1")
                  if p.get("app_namespace") != "porth-platform"]
    markers = {e: ems.get(tenants, {"PK": f"ENV#{s}#PRAWF#DATASET#{e}", "SK": "CURRENT"}) for e in ("porth-org", "porth-tenant")}

    checks = [
        (f"organisation {args.org!r} in {s}", check_org(org, args.org, org_expected)),
        (f"tenant {args.tenant!r} as Porth 0.3.1 writes it", check_tenant(tenant, s, args.tenant, org, tenant_expected)),
        ("tenant-admin role, claim value and grants", check_admin_role(
            roles, grants, registered, tenant_expected["admin_role_source_key"] if tenant_expected else None)),
        ("the adapter's dataset markers", [f"no dataset marker for {e}" for e, m in markers.items() if not m]),
        ("every row Porth's tenant directory loads is readable", check_directory(ems.directory(tenants))),
    ]
    failed = 0
    for name, problems in checks:
        failed += bool(problems)
        print(f"{'FAIL' if problems else 'pass'}  {name}")
        for p in problems:
            print(f"        - {p}")
    for entity, m in markers.items():
        if m:
            print(f"      {entity}: dataset {m['dataset_id']} {m['version']} ({m['digest'][:19]}...), seeded by {m['run_id']}")
    print(f"\n{len(checks) - failed} of {len(checks)} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
