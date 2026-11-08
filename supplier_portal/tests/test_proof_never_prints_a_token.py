"""scripts/supplier_proof.py never prints a Porth session token.

The repository is public, so supplier-proof.yml's log is too. On 2026-11-08 the S3
line printed the second supplier's whole mint answer, token included.
"""

import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
TOKEN = "prth_fake-token-for-the-redaction-test_0123456789"


@pytest.fixture()
def proof(monkeypatch):
    for name, value in {"ENVIRONMENT_SLOT": "porth-dau", "API_APEX": "porth-dau.example",
                        "TENANT": "ems-test", "BUYER": "b"}.items():
        monkeypatch.setenv(name, value)
    spec = importlib.util.spec_from_file_location("supplier_proof", ROOT / "scripts" / "supplier_proof.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_token_in_a_detail_is_redacted(proof, capsys):
    proof.ok("S3 a second supplier's contact gets a session", True,
             f"200 {{'token': '{TOKEN}', 'session_id': 's'}}")
    out = capsys.readouterr().out
    assert TOKEN not in out and "prth_<redacted>" in out


def test_a_failing_check_is_redacted_too(proof, capsys):
    with pytest.raises(SystemExit):
        proof.ok("prerequisites", False, f"500 {{'token': '{TOKEN}'}}")
    assert TOKEN not in capsys.readouterr().out


def test_the_supplier_s_permissions_come_from_roles_json(proof):
    assert sorted(proof.SUPPLIER_PERMISSIONS) == ["supplier.invoices.read", "supplier.invoices.submit"]
