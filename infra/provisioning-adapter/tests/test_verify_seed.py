"""scripts/verify_seed.py's checks, against the rows a real seed writes (porth-common 0.0.9 on moto).

The script reads EMS's tables with the aws CLI; its checks are pure functions over the items, so they
are tested here on exactly what the adapter writes - read back raw, in the DynamoDB JSON the CLI
returns - and on broken copies, so a check that cannot fail is caught too.
"""
import copy
import importlib.util
import sys
from pathlib import Path

import boto3

from test_porth_org import ems_org
from test_porth_tenant import SLOT, TABLES, call, ems_test, porth  # noqa: F401 - porth is a fixture

_spec = importlib.util.spec_from_file_location(
    "verify_seed", Path(__file__).resolve().parents[1] / "scripts" / "verify_seed.py")
verify = importlib.util.module_from_spec(_spec)
sys.modules["verify_seed"] = verify
_spec.loader.exec_module(verify)


def raw_query(table, attr, value, index=None):
    kwargs = {"TableName": table, "KeyConditionExpression": f"{attr} = :v", "ExpressionAttributeValues": {":v": {"S": value}}}
    if index:
        kwargs["IndexName"] = index
    return [verify.item(i) for i in boto3.client("dynamodb").query(**kwargs)["Items"]]


def read(slug="ems-fixtures", tenant_id="ems-test"):
    ddb = boto3.client("dynamodb")
    (org,) = raw_query(TABLES["tenants"], "gsi1pk", f"ENV#{SLOT}#ORG_SLUG#{slug}", index="gsi1")
    tenant = verify.item(ddb.get_item(TableName=TABLES["tenants"],
                                      Key={"PK": {"S": f"ENV#{SLOT}#TENANT#{tenant_id}"}, "SK": {"S": "METADATA"}})["Item"])
    roles = [r for r in raw_query(TABLES["roles"], "pk", f"ENV#{SLOT}#TENANT#{tenant_id}") if r["sk"].startswith("ROLE#")]
    admin = next(r for r in roles if r["name"] == "tenant-admin")
    grants = [g["permission_key"] for g in raw_query(TABLES["roles"], "pk", f"ENV#{SLOT}#TENANT#{tenant_id}#ROLE#{admin['id']}")]
    registered = [p["key"] for p in raw_query(TABLES["permissions"], "gsi1pk", f"ENV#{SLOT}#TENANT#{tenant_id}", index="gsi1")]
    directory = [verify.item(i) for i in ddb.scan(TableName=TABLES["tenants"])["Items"]
                 if i["SK"]["S"] == "METADATA" and "TENANT#" in i["PK"]["S"]]
    return org, tenant, roles, grants, registered, directory


def seed_both():
    call("seed", {"dataset": ems_org()}, entity="porth-org")
    call("seed", {"dataset": ems_test(org="ems-fixtures")})


def test_every_check_passes_on_what_a_seed_writes(porth):
    seed_both()
    org, tenant, roles, grants, registered, directory = read()
    expected = {"display_name": "EMS Test Tenant", "tenant_tier": "development"}
    assert verify.check_org(org, "ems-fixtures", "EMS Fixtures") == []
    assert verify.check_tenant(tenant, SLOT, "ems-test", org, expected) == []
    assert verify.check_admin_role(roles, grants, registered, "tenant-admin") == []
    assert verify.check_directory(directory) == []


def test_a_missing_seed_is_reported(porth):
    assert verify.check_org(None, "ems", None) == ["no organisation with slug 'ems'"]
    assert verify.check_tenant(None, SLOT, "ems-test", None, None)


def test_each_check_can_fail(porth):
    seed_both()
    org, tenant, roles, grants, registered, directory = read()

    unlisted = {k: v for k, v in tenant.items() if not k.startswith("gsi2")}
    assert any("gsi2" in p for p in verify.check_tenant(unlisted, SLOT, "ems-test", org, None))

    elsewhere = {**tenant, "org_id": "some-other-org"}
    assert any("org_id" in p for p in verify.check_tenant(elsewhere, SLOT, "ems-test", org, None))

    assert any("display_name" in p for p in verify.check_tenant(
        tenant, SLOT, "ems-test", org, {"display_name": "Something else", "tenant_tier": "development"}))

    assert any("holds" in p for p in verify.check_admin_role(roles, grants[:1], registered, None))
    assert any("answers to" in p for p in verify.check_admin_role(roles, grants, registered, "someone-else"))

    renamed = [{**org, "name": "Not EMS"}]
    assert verify.check_org(renamed[0], "ems-fixtures", "EMS Fixtures")


def test_the_directory_check_catches_the_row_that_stops_every_login(porth):
    seed_both()
    *_, directory = read()
    poisoned = copy.deepcopy(directory) + [{**directory[0], "tenant_id": "bad", "tenant_tier": "standard"}]
    problems = verify.check_directory(poisoned)
    assert problems and all("bad" in p for p in problems), problems


def test_dynamodb_json_is_read_as_the_cli_returns_it():
    raw = {"PK": {"S": "x"}, "is_system": {"BOOL": True}, "n": {"N": "3"}, "m": {"M": {"a": {"L": [{"S": "b"}]}}},
           "z": {"NULL": True}}
    assert verify.item(raw) == {"PK": "x", "is_system": True, "n": "3", "m": {"a": ["b"]}, "z": None}
