#!/usr/bin/env python3
"""Remove what bootstrap_platform_tenant.py wrote for ONE environment scope.

    PORTH_ENV_SCOPE=porth-tenant python3 scripts/purge_env_scope.py [--apply]

PORTH-656. #150 invented a `porth-tenant` environment, and the install's bootstrap
wrote a platform tenant for it under ENV#porth-tenant#…. That environment does
not exist, so those rows are removed — and only those.

Not reset-env.yml: its cleanup Lambda empties whole tables, every environment
included, whatever env_scope it is given.

Scoped by construction. Every key below is ENV#{scope}#… built from the same
templates the bootstrap writes with, read by Query (never Scan), and each item is
checked to carry the prefix before it is deleted. Environments that exist are
refused outright. Dry-run unless --apply: the plan lists every item first.
"""
from __future__ import annotations

import os
import re
import sys

import boto3
from boto3.dynamodb.conditions import Key

#: Environments that exist. Their data is never touched here, whatever is asked.
PROTECTED = {"porth-sample", "porth-dau", "prod"}
APP_NS = "porth-platform"  # bootstrap_platform_tenant.APP_NS


def _query(table, key_name: str, pk: str) -> list[dict]:
    items, kwargs = [], {"KeyConditionExpression": Key(key_name).eq(pk)}
    while True:
        resp = table.query(**kwargs)
        items += resp.get("Items", [])
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def plan(scope: str, tables: dict) -> list[tuple[str, object, dict]]:
    """(table name, table, key) for every item the bootstrap wrote under *scope*."""
    p = f"ENV#{scope}#"
    found: list[tuple[str, object, dict]] = []

    def collect(name: str, hash_key: str, range_key: str, pk: str) -> list[dict]:
        table = tables[name]
        rows = _query(table, hash_key, pk)
        for r in rows:
            found.append((table.name, table, {hash_key: r[hash_key], range_key: r[range_key]}))
        return rows

    tenant_rows = collect("tenants", "PK", "SK", f"{p}TENANT#platform")
    for r in tenant_rows:
        if r.get("org_id"):
            collect("tenants", "PK", "SK", f"{p}ORG#{r['org_id']}")

    collect("permissions", "pk", "sk", f"{p}TENANT#platform#NS#{APP_NS}")

    role_rows = collect("roles", "pk", "sk", f"{p}TENANT#platform")
    for r in role_rows:
        if str(r["sk"]).startswith("ROLE#"):
            collect("roles", "pk", "sk", f"{p}TENANT#platform#ROLE#{r['sk'][len('ROLE#'):]}")

    collect("claim_mapping", "pk", "sk", f"{p}TENANT#platform")

    for _, _, key in found:
        pk = next(iter(key.values()))
        if not str(pk).startswith(p):  # belt and braces: never outside the scope
            raise SystemExit(f"::error::refusing: {key} is outside {p}")
    return found


def main(argv: list[str]) -> int:
    apply = "--apply" in argv
    scope = os.environ.get("PORTH_ENV_SCOPE", "").strip()
    if not re.fullmatch(r"[a-z][a-z0-9-]*", scope):
        raise SystemExit(f"::error::PORTH_ENV_SCOPE {scope!r} is not an environment slot")
    if scope in PROTECTED:
        raise SystemExit(f"::error::{scope} is a live environment; this script never purges it")

    ddb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    tables = {
        "tenants": ddb.Table(os.environ["PORTH_TENANTS_TABLE"]),
        "permissions": ddb.Table(os.environ["PORTH_PERMISSIONS_TABLE"]),
        "roles": ddb.Table(os.environ["PORTH_ROLES_TABLE"]),
        "claim_mapping": ddb.Table(os.environ["PORTH_CLAIM_MAPPING_CONFIGS_TABLE"]),
    }

    items = plan(scope, tables)
    print(f"{len(items)} item(s) under ENV#{scope}#:")
    for name, _, key in items:
        print(f"  {name}: {key}")
    if not items:
        print("nothing to do")
        return 0
    if not apply:
        print("(dry run — nothing deleted; re-run with apply to delete exactly these)")
        return 0
    for name, table, key in items:
        table.delete_item(Key=key)
        print(f"  deleted {name}: {key}")
    print(f"✅ purged {len(items)} item(s) under ENV#{scope}#")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
