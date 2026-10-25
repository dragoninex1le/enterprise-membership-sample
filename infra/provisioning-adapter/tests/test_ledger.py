"""prawf's bookkeeping lives in prawf's own audit table, never in Porth's (Richard, 2026-10-25).

A test tool's rows in the application's tables are state the application never agreed to hold, read
by code that never expected them. So: seed, teardown and reset write nothing of prawf's to any Porth
table; the audit table holds which run wrote what and which dataset each entity carries; and a full
reset clears the rows an earlier adapter left in Porth's tenants table before it had a table of its own.
"""
import boto3

from test_porth_org import ems_org
from test_porth_platform import install
from test_porth_tenant import AUDIT, ORG_ID, SLOT, TABLES, call, ems_test, porth  # noqa: F401 - porth is a fixture


def porth_rows_of_prawf():
    return [(name, item.get("PK") or item.get("pk")) for name in TABLES.values()
            for item in boto3.resource("dynamodb").Table(name).scan()["Items"]
            if "PRAWF#" in (item.get("PK") or item.get("pk"))]


def audit():
    return {(i["PK"], i["SK"]) for i in boto3.resource("dynamodb").Table(AUDIT).scan()["Items"]}


def seed_both(run_id="run-seed-1"):
    assert call("seed", {"dataset": ems_org()}, run_id=run_id, entity="porth-org")["outcome"] == "ok"
    assert call("seed", {"dataset": ems_test(org="ems-fixtures")}, run_id=run_id)["outcome"] == "ok"


def test_a_seed_writes_nothing_of_prawfs_to_porths_tables(porth):
    seed_both()
    assert porth_rows_of_prawf() == []
    assert audit() == {
        (f"ENV#{SLOT}#ENTITY#porth-org", "RUN#run-seed-1"), (f"ENV#{SLOT}#ENTITY#porth-org", "DATASET"),
        (f"ENV#{SLOT}#ENTITY#porth-tenant", "RUN#run-seed-1"), (f"ENV#{SLOT}#ENTITY#porth-tenant", "DATASET"),
    }


def test_the_audit_record_says_which_run_wrote_what_and_when(porth):
    seed_both()
    t = boto3.resource("dynamodb").Table(AUDIT)
    run = t.get_item(Key={"PK": f"ENV#{SLOT}#ENTITY#porth-tenant", "SK": "RUN#run-seed-1"})["Item"]
    assert run["run_id"] == "run-seed-1" and run["started_at"] and run["writes"]
    marker = t.get_item(Key={"PK": f"ENV#{SLOT}#ENTITY#porth-tenant", "SK": "DATASET"})["Item"]
    assert (marker["run_id"], marker["version"]) == ("run-seed-1", "1.0.0") and marker["applied_at"]


def test_teardown_clears_the_runs_audit_record_and_nothing_else(porth):
    seed_both()
    call("teardown", {"run_id": "run-seed-1"}, run_id="run-teardown-1", entity=None)
    assert audit() == set()
    assert porth_rows_of_prawf() == []


def _install_and_seed(monkeypatch):
    """A slot as the install leaves it, with a prawf fixture seeded."""
    t = boto3.resource("dynamodb").Table(TABLES["tenants"])
    t.delete_item(Key={"PK": f"ENV#{SLOT}#TENANT#platform", "SK": "METADATA"})
    t.delete_item(Key={"PK": f"ENV#{SLOT}#ORG#{ORG_ID}", "SK": "METADATA"})
    install(monkeypatch)
    seed_both()


def _strays():
    """What the PRF-12 to PRF-14 adapter wrote into Porth's tenants table."""
    t = boto3.resource("dynamodb").Table(TABLES["tenants"])
    rows = [{"PK": f"ENV#{SLOT}#PRAWF#RUN#run-old", "SK": "LEDGER#porth-org", "writes": []},
            {"PK": f"ENV#{SLOT}#PRAWF#RUN#run-old", "SK": "LEDGER#porth-tenant", "writes": []},
            {"PK": f"ENV#{SLOT}#PRAWF#DATASET#porth-tenant", "SK": "CURRENT", "dataset_id": "x"}]
    for r in rows:
        t.put_item(Item=r)
    return rows


def reset(entity=None, dry_run=False):
    return call("reset", {"confirm_environment_class": "disposable"}, run_id="run-reset-1", dry_run=dry_run, entity=entity)


def test_a_full_reset_clears_the_audit_record_and_the_rows_an_earlier_adapter_left_in_porth(porth, monkeypatch):
    _install_and_seed(monkeypatch)
    _strays()
    response = reset()
    assert response["outcome"] == "ok"
    assert porth_rows_of_prawf() == []
    assert audit() == set()
    assert any("removed 3 prawf row(s)" in m for m in response["diagnostics"]["messages"])


def test_a_dry_run_reset_lists_the_strays_and_removes_nothing(porth, monkeypatch):
    _install_and_seed(monkeypatch)
    _strays()
    response = reset(dry_run=True)
    assert len(porth_rows_of_prawf()) == 3
    assert any("would remove 3 prawf row(s)" in m for m in response["diagnostics"]["messages"])


def test_a_scoped_reset_clears_its_own_audit_record_and_leaves_the_strays(porth, monkeypatch):
    """C16: the strays are every entity's, so only a full reset takes them."""
    _install_and_seed(monkeypatch)
    _strays()
    reset(entity="porth-claim-mapping")
    reset(entity="porth-tenant")
    assert len(porth_rows_of_prawf()) == 3
    assert {pk for pk, _ in audit()} == {f"ENV#{SLOT}#ENTITY#porth-org"}, "porth-org's record stays with its rows"
