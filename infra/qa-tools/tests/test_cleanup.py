"""QA cleanup: which tables it will empty, and that a dry run counts without deleting.

Richard, 2026-11-10: a reset clears every table EMS holds - Porth's, EMS's own per slot, and prawf's
ledger - so the install can start from nothing and be bootstrapped clean.

A stand-in table, not moto: the QA tools' CI installs pytest and boto3 only.
"""
import importlib.util
import json
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "cleanup_handler", Path(__file__).resolve().parents[1] / "src" / "cleanup" / "handler.py")
cleanup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cleanup)


class FakeTable:
    def __init__(self, rows):
        self.key_schema = [{"AttributeName": "PK"}, {"AttributeName": "SK"}]
        self.rows = [{"PK": f"ENV#porth-dau#ROW#{i}", "SK": "X"} for i in range(rows)]

    def scan(self, **_):
        return {"Items": list(self.rows)}

    def batch_writer(self):
        table = self

        class Batch:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def delete_item(self, Key):
                table.rows.remove(Key)

        return Batch()


@pytest.fixture
def tables(monkeypatch):
    monkeypatch.setenv("PORTH_ENV", "dev")
    held = {}

    class Resource:
        def Table(self, name):
            return held.setdefault(name, FakeTable(3))

    monkeypatch.setattr(cleanup.boto3, "resource", lambda *a, **k: Resource())
    return held


def call(name, **extra):
    out = cleanup.handler({"body": json.dumps({"table_name": name, **extra})}, None)
    return out["statusCode"], json.loads(out["body"])


@pytest.mark.parametrize("name", ["porth-tenants-dev", "porth-audit-log-dev", "ems-sample-app-porth-dau",
                                  "ems-supplier-links-porth-sample", "ems-ffug-porth-dau", "prawf-adapter-audit"])
def test_every_table_ems_holds_is_emptied(tables, name):
    assert call(name) == (200, {"deleted": 3, "table": name, "prefix": None, "dry_run": False})
    assert tables[name].rows == []


def test_a_dry_run_counts_and_deletes_nothing(tables):
    status, body = call("ems-ffug-porth-dau", dry_run=True)
    assert (status, body["deleted"], body["dry_run"]) == (200, 3, True)
    assert len(tables["ems-ffug-porth-dau"].rows) == 3


@pytest.mark.parametrize("name", ["porth-tenants-prod", "porth-tenants-staging", "ems-sample-app",
                                  "ems-other-porth-dau", "prawf-runs", "elegans-orders-dev", "ems-ffug-prod"])
def test_anything_else_is_refused(tables, name):
    status, body = call(name)
    assert status in (400, 403) and "Refused" in body["error"]
    assert name not in tables, "refused before the table is touched"
