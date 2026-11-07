"""PORTH-656 — the install's /porth/auth seed never drops the managed keys.

porth-install.yml overwrites /porth/auth, then `porth-install auth-config` writes
root_url / environments / tenant_origins back ~12 s later. Built without them,
the live blob lacked them for that window, and a Porth Lambda re-reading it
(60 s TTL) stopped recognising tenant API hosts for up to a minute, on every
install (EMS 0.4.7 install, 2026-11-07). The builder now carries them over.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "build_auth_blob", ROOT / "deploy/porth/scripts/build_auth_blob.py"
)
build_auth_blob = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_auth_blob)

MANIFEST = {"platform": {"idp": {"issuer": "https://i/", "jwks_uri": "https://i/jwks", "client_id": "c"}}}
ENV = {"PORTH_DNS_ZONE": "ems.estynsoftware.cloud", "PORTH_DOMAIN": "porth-api.ems.estynsoftware.cloud"}
LIVE = {
    "issuer": "https://old/", "root_url": "ems.estynsoftware.cloud",
    "environments": "porth-sample,porth-dau", "tenant_origins": "required",
}


def test_the_live_managed_keys_are_carried_over():
    blob = build_auth_blob.build(MANIFEST, {**ENV, "EXISTING_AUTH_BLOB": json.dumps(LIVE)})
    assert blob["root_url"] == "ems.estynsoftware.cloud"
    assert blob["environments"] == "porth-sample,porth-dau"
    assert blob["tenant_origins"] == "required"


def test_only_the_managed_keys_are_carried_everything_else_is_rebuilt():
    blob = build_auth_blob.build(MANIFEST, {**ENV, "EXISTING_AUTH_BLOB": json.dumps(LIVE)})
    assert blob["issuer"] == "https://i/", "the manifest still decides identity"


def test_a_first_install_carries_nothing_and_decides_nothing():
    blob = build_auth_blob.build(MANIFEST, ENV)
    assert not set(build_auth_blob.MANAGED_KEYS) & set(blob)


def test_an_unreadable_live_blob_carries_nothing():
    blob = build_auth_blob.build(MANIFEST, {**ENV, "EXISTING_AUTH_BLOB": "not json"})
    assert not set(build_auth_blob.MANAGED_KEYS) & set(blob)
