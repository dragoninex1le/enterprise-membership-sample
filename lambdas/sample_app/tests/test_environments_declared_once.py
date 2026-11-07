"""PORTH-656 — the environments EMS deploys are declared once and read from main."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("environments", ROOT / "scripts/environments.py")
environments = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(environments)

DECLARED = (ROOT / "deploy/porth/environments.json").read_text()


def _envs(text=DECLARED):
    return environments.load(text, text, warn=lambda m: None)


def test_main_deploys_porth_sample_and_any_other_branch_porth_dau():
    envs = _envs()
    assert environments.slot_for_ref(envs, "refs/heads/main") == "porth-sample"
    assert environments.slot_for_ref(envs, "refs/heads/PORTH-656/anything") == "porth-dau"


def test_the_two_environments_ems_has_and_no_other():
    """There is no porth-tenant (2026-11-06)."""
    assert set(_envs()) == {"porth-sample", "porth-dau"}


def test_a_branchs_own_edit_is_ignored_and_named():
    edited = json.loads(DECLARED)
    edited["environments"]["porth-tenant"] = {"deploys_from": "porth-tenant", "tenant_api_hosts": True}
    warnings = []
    envs = environments.load(DECLARED, json.dumps(edited), warn=warnings.append)
    assert "porth-tenant" not in envs
    assert warnings and "IGNORED" in warnings[0]


def test_before_the_file_reaches_main_the_working_copy_is_used_with_a_warning():
    warnings = []
    assert set(environments.load(None, DECLARED, warn=warnings.append)) == {"porth-sample", "porth-dau"}
    assert warnings


def test_resolve_refuses_an_undeclared_slot():
    with pytest.raises(SystemExit):
        environments.resolve(_envs(), "refs/heads/x", override="porth-tenant")


def test_resolve_refuses_when_the_workflow_rule_disagrees():
    with pytest.raises(SystemExit):
        environments.resolve(_envs(), "refs/heads/main", expected="porth-dau")


def test_resolve_carries_tenant_api_hosts():
    assert environments.resolve(_envs(), "refs/heads/feature")["TENANT_API_HOSTS"] == "true"


def test_two_catch_all_environments_are_refused():
    doc = json.loads(DECLARED)
    doc["environments"]["porth-sample"]["deploys_from"] = "other-branches"
    with pytest.raises(SystemExit):
        environments.load(json.dumps(doc), json.dumps(doc), warn=lambda m: None)


def test_a_malformed_copy_on_the_branch_is_ignored_not_fatal():
    warnings = []
    envs = environments.load(DECLARED, "{not json", warn=warnings.append)
    assert set(envs) == {"porth-sample", "porth-dau"} and warnings
