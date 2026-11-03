"""`bootstrap` on porth-platform (PRF-11), against the install that defines the baseline.

The baseline is whatever EMS's Porth install writes - scripts/bootstrap_platform_tenant.py, then the
IdP step of porth-bootstrap.yml. So these tests run that script for real, on moto, and hold the
adapter to it: from nothing, the adapter writes the same rows the install does; on a slot the
install bootstrapped, it writes nothing at all; and its constants are the script's.
"""
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
import pytest

from test_porth_tenant import AUTH, ORG_ID, SLOT, TABLES, call, porth  # noqa: F401 - porth is a fixture

import porth_platform  # noqa: E402 - on the path through test_adapter

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


def clear_platform():
    """The fixture's slot without its platform rows - as if the install had never run."""
    t = boto3.resource("dynamodb").Table(TABLES["tenants"])
    t.delete_item(Key={"PK": f"ENV#{SLOT}#TENANT#platform", "SK": "METADATA"})


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_STAMPS = {"created_at", "updated_at", "assigned_at", "compiled_at"}


def platform_rows(scope):
    """Every platform row under a scope, with ids and timestamps blanked so two installs compare."""
    out = set()
    for kind, name in TABLES.items():
        for item in boto3.resource("dynamodb").Table(name).scan()["Items"]:
            pk = item.get("PK") or item.get("pk")
            if not pk.startswith(f"ENV#{scope}#") or ORG_ID in pk or "PRAWF#" in pk:
                continue
            clean = {k: v for k, v in item.items() if k not in _STAMPS}
            text = json.dumps(clean, sort_keys=True, default=str).replace(f"ENV#{scope}#", "ENV#<s>#")
            out.add((kind, _UUID.sub("<uuid>", text)))
    return out


def bootstrap(dry_run=False, run_id="run-boot-1", payload=None):
    return call("bootstrap", payload, run_id=run_id, dry_run=dry_run, entity="porth-platform")


def outcomes(response):
    return {h["type"]: h["outcome"] for h in response["results"]}


# ---------------------------------------------------------------- the install is the definition

def test_the_constants_are_the_install_scripts(porth, monkeypatch):
    monkeypatch.setenv("PORTH_ROLES_NAMESPACE", NAMESPACE)
    spec = importlib.util.spec_from_file_location("bootstrap_platform_tenant_constants", SCRIPT)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert porth_platform.PERMISSIONS == script.PERMISSIONS
    assert porth_platform.APP_NS == script.APP_NS
    assert porth_platform.mapping_source(NAMESPACE) == script.MAPPING_SOURCE
    assert porth_platform.compiled_source(NAMESPACE) == script.COMPILED_SOURCE
    assert porth_platform.compiled_hash(NAMESPACE) == script.COMPILED_HASH


def test_from_nothing_bootstrap_writes_exactly_what_the_install_writes(porth, monkeypatch):
    install(monkeypatch, scope="porth-reference")
    clear_platform()
    response = bootstrap()
    assert response["outcome"] == "ok"
    assert set(outcomes(response).values()) == {"created"}
    assert platform_rows(SLOT) == platform_rows("porth-reference")
    assert len(platform_rows(SLOT)) == 1 + 1 + 10 + 1 + 10 + 1  # org, tenant, permissions, role, grants, claim mapping


def test_a_slot_the_install_bootstrapped_is_unchanged_and_nothing_is_written(porth, monkeypatch):
    clear_platform()
    install(monkeypatch)
    before = platform_rows(SLOT)
    response = bootstrap()
    assert set(outcomes(response).values()) == {"unchanged"}, outcomes(response)
    assert "nothing written" in response["diagnostics"]["messages"][0]
    assert platform_rows(SLOT) == before


def test_bootstrap_again_is_unchanged(porth):
    clear_platform()
    bootstrap()
    again = bootstrap(run_id="run-boot-2")
    assert set(outcomes(again).values()) == {"unchanged"}


def test_a_dry_run_writes_nothing_and_says_what_it_would(porth):
    clear_platform()
    before = platform_rows(SLOT)
    response = bootstrap(dry_run=True)
    assert response["outcome"] == "ok"
    assert platform_rows(SLOT) == before
    (message,) = response["diagnostics"]["messages"]
    assert message.startswith("dry run: would write") and "Nothing written" in message
    assert "the platform tenant" in message and "permission platform.orgs.read" in message


# ---------------------------------------------------------------- repair, without taking anything

def _role_id():
    roles = boto3.resource("dynamodb").Table(TABLES["roles"]).query(
        KeyConditionExpression="pk = :pk", ExpressionAttributeValues={":pk": f"ENV#{SLOT}#TENANT#platform"})["Items"]
    return next(r["id"] for r in roles if r.get("name") == "platform-admin")


def test_it_completes_a_broken_baseline_and_leaves_the_apps_grants_alone(porth, monkeypatch):
    clear_platform()
    install(monkeypatch)
    res = boto3.resource("dynamodb")
    role_pk = f"ENV#{SLOT}#TENANT#platform#ROLE#{_role_id()}"
    res.Table(TABLES["roles"]).put_item(Item={"pk": role_pk, "sk": f"PERM#{APP_GRANT}", "permission_key": APP_GRANT,
                                              "role_id": _role_id(), "tenant_id": "platform"})
    res.Table(TABLES["permissions"]).delete_item(
        Key={"pk": f"ENV#{SLOT}#TENANT#platform#NS#porth-platform", "sk": "PERM#platform.orgs.delete"})
    res.Table(TABLES["roles"]).delete_item(Key={"pk": role_pk, "sk": "PERM#platform.tenants.read"})
    res.Table(TABLES["tenants"]).update_item(Key={"PK": f"ENV#{SLOT}#TENANT#platform", "SK": "METADATA"},
                                             UpdateExpression="REMOVE role_type")

    response = bootstrap()
    got = outcomes(response)
    assert (got["tenant"], got["porth.permission"], got["porth.role-grant"]) == ("updated", "updated", "updated")
    assert (got["porth.org"], got["porth.role"], got["porth.claim-mapping"]) == ("unchanged", "unchanged", "unchanged")
    tenant = res.Table(TABLES["tenants"]).get_item(Key={"PK": f"ENV#{SLOT}#TENANT#platform", "SK": "METADATA"})["Item"]
    assert tenant["role_type"] == "platform-admin"
    grants = {g["sk"] for g in res.Table(TABLES["roles"]).query(
        KeyConditionExpression="pk = :pk", ExpressionAttributeValues={":pk": role_pk})["Items"]}
    assert f"PERM#{APP_GRANT}" in grants, "another namespace's grant is never removed (PORTH-609)"
    assert {f"PERM#{p['key']}" for p in porth_platform.PERMISSIONS} <= grants
    assert set(outcomes(bootstrap(run_id="run-boot-2")).values()) == {"unchanged"}


def test_a_changed_idp_is_written_back_from_porth_auth(porth, monkeypatch):
    clear_platform()
    install(monkeypatch)
    moved = {**AUTH, "issuer": "https://idp.moved.test/"}
    boto3.client("ssm").put_parameter(Name="/porth/auth", Type="String", Value=json.dumps(moved), Overwrite=True)
    assert outcomes(bootstrap())["tenant"] == "updated"
    tenant = boto3.resource("dynamodb").Table(TABLES["tenants"]).get_item(
        Key={"PK": f"ENV#{SLOT}#TENANT#platform", "SK": "METADATA"})["Item"]
    assert tenant["idp_config_override"]["issuer"] == "https://idp.moved.test/"


def test_a_changed_audience_writes_a_new_claim_mapping_version(porth, monkeypatch):
    clear_platform()
    install(monkeypatch)
    boto3.client("ssm").put_parameter(Name="/porth/auth", Type="String", Overwrite=True,
                                      Value=json.dumps({**AUTH, "audience": "https://api.renamed.test"}))
    assert outcomes(bootstrap())["porth.claim-mapping"] == "updated"
    versions = boto3.resource("dynamodb").Table(TABLES["claims"]).query(
        KeyConditionExpression="PK = :pk", ExpressionAttributeValues={":pk": f"ENV#{SLOT}#TENANT#platform"})["Items"]
    assert sorted(int(v["version"]) for v in versions) == [1, 2]
    assert max(versions, key=lambda v: v["version"])["mapping_source"]["fields"][0]["source"] == "https://api.renamed.test/roles"


def test_legacy_grants_are_swept_and_anyone_elses_moved(porth, monkeypatch):
    clear_platform()
    install(monkeypatch)
    roles = boto3.resource("dynamodb").Table(TABLES["roles"])
    legacy_pk = f"ENV#{SLOT}#ROLE#{_role_id()}"
    roles.put_item(Item={"pk": legacy_pk, "sk": "PERM#platform.tenants.read", "permission_key": "platform.tenants.read"})
    roles.put_item(Item={"pk": legacy_pk, "sk": f"PERM#{APP_GRANT}", "permission_key": APP_GRANT})
    assert outcomes(bootstrap())["porth.role-grant"] == "updated"
    assert roles.query(KeyConditionExpression="pk = :pk", ExpressionAttributeValues={":pk": legacy_pk})["Items"] == []
    moved = roles.get_item(Key={"pk": f"ENV#{SLOT}#TENANT#platform#ROLE#{_role_id()}", "sk": f"PERM#{APP_GRANT}"})
    assert "Item" in moved


# ---------------------------------------------------------------- refusals, and what it never does

def test_a_payload_is_refused_before_anything_is_read(porth):
    response = bootstrap(payload={"dataset": {"id": "x"}})
    assert (response["outcome"], response["reason_code"]) == ("refused", "dataset_conflict")


def test_without_porth_auth_it_fails_loudly_and_writes_nothing(porth):
    clear_platform()
    boto3.client("ssm").delete_parameter(Name="/porth/auth")
    before = platform_rows(SLOT)
    response = bootstrap()
    assert (response["outcome"], response["reason_code"]) == ("failed", "upstream_error")
    assert "/porth/auth" in response["diagnostics"]["messages"][0]
    assert platform_rows(SLOT) == before


def test_the_baseline_is_no_runs_fixture_so_teardown_leaves_it(porth):
    clear_platform()
    bootstrap(run_id="run-boot-1")
    before = platform_rows(SLOT)
    call("teardown", {"run_id": "run-boot-1"}, run_id="run-teardown-1", entity=None)
    assert platform_rows(SLOT) == before


def test_no_response_carries_the_idp_client_id_beyond_its_handle(porth):
    """The blob's client id is configuration, not a credential - but nothing about it is echoed."""
    clear_platform()
    blob = json.dumps(bootstrap())
    assert AUTH["interactive_client_id"] not in blob
