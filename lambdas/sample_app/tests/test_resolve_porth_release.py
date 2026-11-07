"""PORTH-656 — the install runs the porth-install its Porth release was cut with.

scripts/resolve-porth-release.sh reads the release manifest; these run it against
a stub `aws` that serves a manifest, and read what it hands the workflow.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "resolve-porth-release.sh"
BUCKET = "porth-releases-084847995635"


def _run(tmp_path: Path, manifest: dict, version: str = "0.4.12"):
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    stub = tmp_path / "bin" / "aws"
    stub.parent.mkdir()
    # `aws s3 cp s3://… <dest> …` → copy the manifest to <dest>.
    stub.write_text(f'#!/usr/bin/env bash\ncp "{tmp_path}/manifest.json" "$4"\n')
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    out, env_file = tmp_path / "out", tmp_path / "env"
    env = {**os.environ, "PATH": f"{stub.parent}:{os.environ['PATH']}",
           "GITHUB_OUTPUT": str(out), "GITHUB_ENV": str(env_file), "AWS_REGION": "us-east-1"}
    env.pop("GITHUB_STEP_SUMMARY", None)
    proc = subprocess.run(["bash", str(SCRIPT), version], env=env, capture_output=True, text=True)
    read = lambda p: dict(l.split("=", 1) for l in p.read_text().splitlines()) if p.exists() else {}
    return proc, read(out), read(env_file)


def _manifest(version="0.4.12", porth_install="0.4.7"):
    m = {"version": version, "image": "x", "git_sha": "a" * 40,
         "template_url": f"https://{BUCKET}.s3.us-east-1.amazonaws.com/porth/{version}/template.yaml"}
    if porth_install is not None:
        m["components"] = {"porth-install": porth_install, "porth-common": "0.0.23"}
    return m


def test_the_porth_install_version_comes_from_the_release(tmp_path):
    proc, out, env = _run(tmp_path, _manifest())
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert out["porth_install_version"] == "0.4.7"
    assert env["PORTH_INSTALL_VERSION"] == "0.4.7"
    assert out["template_url"].endswith("/porth/0.4.12/template.yaml")


@pytest.mark.parametrize("porth_install", [None, "", "latest"])
def test_a_manifest_without_an_exact_porth_install_is_refused(tmp_path, porth_install):
    proc, out, env = _run(tmp_path, _manifest(porth_install=porth_install))
    assert proc.returncode != 0
    assert "names no porth-install version" in proc.stdout
    assert "PORTH_INSTALL_VERSION" not in env


def test_no_porth_install_pin_is_left_in_the_install_workflows():
    for name in ("porth-install.yml", "porth-admin.yml"):
        text = (REPO / ".github" / "workflows" / name).read_text()
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert not stripped.startswith(("PORTH_INSTALL_VERSION:", "PORTH_INSTALL_CHECK_VERSION: '")), (name, line)
