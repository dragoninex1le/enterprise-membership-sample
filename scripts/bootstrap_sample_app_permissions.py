#!/usr/bin/env python3
"""Register sample app permissions and create roles via the Porth API."""
from __future__ import annotations
import argparse, json, sys, urllib.request, urllib.error

PERMISSIONS = [
    {"key": "dashboard.read",    "display_name": "View Dashboard",       "category": "Dashboard"},
    {"key": "ar.invoices.read",  "display_name": "View Invoices",        "category": "Accounts Receivable"},
    {"key": "ar.invoices.write", "display_name": "Create/Edit Invoices", "category": "Accounts Receivable"},
    {"key": "ap.bills.read",     "display_name": "View Bills",           "category": "Accounts Payable"},
    {"key": "ap.bills.write",    "display_name": "Create/Edit Bills",    "category": "Accounts Payable"},
    {"key": "approvals.read",    "display_name": "View Approval Queue",  "category": "Approvals"},
    {"key": "approvals.write",   "display_name": "Approve/Reject",       "category": "Approvals"},
]

ROLES = [
    {"name": "viewer",       "permissions": ["dashboard.read"]},
    {"name": "ar-clerk",     "permissions": ["dashboard.read", "ar.invoices.read", "ar.invoices.write"]},
    {"name": "ap-clerk",     "permissions": ["dashboard.read", "ap.bills.read", "ap.bills.write"]},
    {"name": "controller",   "permissions": ["dashboard.read", "ar.invoices.read", "ap.bills.read", "approvals.read", "approvals.write"]},
    {"name": "tenant-admin", "permissions": [p["key"] for p in PERMISSIONS]},
]

DEFAULT_CLAIM_MAPPING = {
    "schema_version": "2.0",
    "fields": [
        {
            "name": "roles",
            "source": "https://porth.io/roles",
            "type": "collection",
            "required": False,
            "ops": [{"op": "resolve_roles"}],
        }
    ],
    "default_roles": [],
}

def api_call(base_url, method, path, token, body=None):
    url = f"{base_url.rstrip('/')}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code} {method} {path}: {e.read().decode()}", file=sys.stderr)
        raise

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--api-url", required=True)
    p.add_argument("--tenant-id", required=True)
    p.add_argument("--auth-token", required=True)
    args = p.parse_args()
    print(f"Bootstrapping sample app for tenant {args.tenant_id}...")

    perms = [{**p, "app_namespace": "sample-app"} for p in PERMISSIONS]
    result = api_call(args.api_url, "POST", "/permissions/", args.auth_token,
                      {"tenant_id": args.tenant_id, "app_namespace": "sample-app", "permissions": perms})
    print(f"  Registered {result.get('count', '?')} permissions")

    for role_def in ROLES:
        try:
            role = api_call(args.api_url, "POST", "/roles/", args.auth_token,
                            {"tenant_id": args.tenant_id, "name": role_def["name"]})
            api_call(args.api_url, "PUT", f"/roles/{args.tenant_id}/{role['id']}/permissions",
                     args.auth_token, role_def["permissions"])
            print(f"  Created role '{role_def['name']}'")
        except Exception as e:
            print(f"  Warning: {role_def['name']} skipped: {e}", file=sys.stderr)

    try:
        api_call(args.api_url, "POST", f"/claim-mapping-configs/?tenant_id={args.tenant_id}",
                 args.auth_token, {"mapping_source": DEFAULT_CLAIM_MAPPING})
        print("  Claim mapping config seeded")
    except Exception as e:
        print(f"  Warning: claim mapping skipped: {e}", file=sys.stderr)
    print("Done.")

if __name__ == "__main__":
    main()
