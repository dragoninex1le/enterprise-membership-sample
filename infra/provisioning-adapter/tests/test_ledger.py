"""prawf's bookkeeping lives in prawf's own audit table, never in Porth's (Richard, 2026-10-25).

A test tool's rows in the application's tables are state the application never agreed to hold, read
by code that never expected them. So: seed, teardown and reset write nothing of prawf's to any Porth
table; the audit table holds which run wrote what, which dataset each entity carries, and the
install's baselines; and a reset clears the seed entities' records with their rows, keeps the
baselines, and removes anything an earlier adapter left in Porth's tenants table after the capture.
"""
import boto3

from test_porth_org import ems_org
from test_porth_tenant import AUDIT, ORG_ID, SLOT, TABLES, call, ems_test, porth  # noqa: F401 - porth is a fixture
from porth_install import install


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


def _install_and_capture(monkeypatch):
    """A slot as the install leaves it, captured as its baseline."""
    t = boto3.resource("dynamodb").Table(TABLES["tenants"])
    t.delete_item(Key={"PK": f"ENV#{SLOT}#TENANT#platform", "SK": "METADATA"})
    t.delete_item(Key={"PK": f"ENV#{SLOT}#ORG#{ORG_ID}", "SK": "METADATA"})
    install(monkeypatch)
    boot = call("bootstrap", {"installed_version": "0.3.1"}, entity="porth", contract="1.1", slot=SLOT)
    assert boot["outcome"] == "ok", boot
    return {"installed_version": "0.3.1", "content_digest": boot["results"][0]["content_digest"]}


def _strays():
    """What the PRF-12 to PRF-14 adapter wrote into Porth's tenants table."""
    t = boto3.resource("dynamodb").Table(TABLES["tenants"])
    rows = [{"PK": f"ENV#{SLOT}#PRAWF#RUN#run-old", "SK": "LEDGER#porth-org", "writes": []},
            {"PK": f"ENV#{SLOT}#PRAWF#RUN#run-old", "SK": "LEDGER#porth-tenant", "writes": []},
            {"PK": f"ENV#{SLOT}#PRAWF#DATASET#porth-tenant", "SK": "CURRENT", "dataset_id": "x"}]
    for r in rows:
        t.put_item(Item=r)
    return rows


def test_reset_clears_the_seed_records_and_the_strays_and_keeps_the_baseline(porth, monkeypatch):
    baseline = _install_and_capture(monkeypatch)
    seed_both()
    _strays()
    response = call("reset", {"confirm_environment_class": "disposable", "baseline": baseline},
                    run_id="run-reset-1", entity="porth", contract="1.1", slot=SLOT)
    assert response["outcome"] == "ok", response
    assert porth_rows_of_prawf() == []
    assert audit() == {(f"ENV#{SLOT}#ENTITY#porth", f"BASELINE#0.3.1#{baseline['content_digest']}")}
