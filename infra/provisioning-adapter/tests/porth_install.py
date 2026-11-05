"""EMS's Porth install on moto, for tests that need a slot as a deploy leaves it.

The install is scripts/bootstrap_platform_tenant.py, then the IdP step of porth-bootstrap.yml - run
for real, not copied. The adapter knows none of what it writes: `bootstrap` on `porth` captures it.
"""
import importlib.util
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import boto3

from test_porth_tenant import AUTH, ORG_ID, SLOT, TABLES

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "bootstrap_platform_tenant.py"
NAMESPACE = f"{AUTH['audience']}/roles"
APP_GRANT = "ems.accounts-receivable.read"  # a consuming app's own grant on platform-admin (PORTH-609)


def install(monkeypatch, scope=SLOT):
    """EMS's Porth install, as porth-bootstrap.yml runs it: the shared script, then the IdP patch."""
    monkeypatch.setenv("PORTH_ENV_SCOPE", scope)
    monkeypatch.setenv("PORTH_ROLES_NAMESPACE", NAMESPACE)
    spec = importlib.util.spec_from_file_location(f"bootstrap_platform_tenant_{scope}", SCRIPT)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    script.main()
    boto3.resource("dynamodb").Table(TABLES["tenants"]).update_item(
        Key={"PK": f"ENV#{scope}#TENANT#platform", "SK": "METADATA"},
        UpdateExpression="SET idp_config_override = :idp, tenant_tier = :tier, role_type = :rt, updated_at = :ua",
        ExpressionAttributeValues={
            ":idp": {"issuer": AUTH["issuer"], "jwks_uri": AUTH["jwks_uri"], "client_id": AUTH["interactive_client_id"],
                     "audience": AUTH["audience"], "protocol": AUTH["protocol"]},
            ":tier": "production", ":rt": "platform-admin",
            ":ua": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )
    return script


def role_id(scope=SLOT):
    roles = boto3.resource("dynamodb").Table(TABLES["roles"]).query(
        KeyConditionExpression="pk = :pk", ExpressionAttributeValues={":pk": f"ENV#{scope}#TENANT#platform"})["Items"]
    return next(r["id"] for r in roles if r.get("name") == "platform-admin")


def slot_rows(scope=SLOT, with_sessions=False):
    """Every row of a slot in Porth's tables, exactly as stored, as comparable JSON."""
    out = set()
    for kind, name in TABLES.items():
        if kind == "sessions" and not with_sessions:
            continue
        for item in boto3.client("dynamodb").scan(TableName=name)["Items"]:
            pk = (item.get("PK") or item.get("pk"))["S"]
            if pk.startswith(f"ENV#{scope}#"):
                out.add((kind, json.dumps(item, sort_keys=True, default=str)))
    return out
