#!/usr/bin/env python3
"""The environments EMS deploys — declared once, read from main (PORTH-656).

    environments.py resolve --ref refs/heads/x [--slot override]   KEY=VALUE lines for $GITHUB_ENV
    environments.py list                                             porth-sample,porth-dau
    environments.py tfvars                                           {"tenant_host_slots": [...]}

The porth-install-once Terraform (Components) takes the certificate list as
tenant_host_slots; generate it rather than keeping a copy in a tfvars file:

    python3 scripts/environments.py tfvars > /tmp/ems-slots.tfvars.json
    terraform apply -var-file=ems.tfvars -var-file=/tmp/ems-slots.tfvars.json

deploy/porth/environments.json is the one place the environment list lives. Every
pipeline (the app deploy, the Porth install, the ffug proof) and the Terraform
read it through this script, and `porth-install check` verifies the install
against it.

**Always main's copy.** A branch deploys its CODE to porth-dau; it must not be
able to redefine which environments exist or how they are served by editing its
own copy. So the file is read from origin/main. A branch whose copy differs is
warned, by name, so an edit there does not silently do nothing. Changing the set
is a merge to main and a porth-install run.

Until the file reaches main (the PR that adds it), the working copy is used, with
a warning.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PATH = "deploy/porth/environments.json"
MAIN = "origin/main"
OTHER_BRANCHES = "other-branches"


def _git_show(ref: str) -> str | None:
    try:
        return subprocess.run(
            ["git", "show", f"{ref}:{PATH}"], check=True, capture_output=True, text=True
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def load(main_text: str | None, working_text: str | None, warn=print) -> dict:
    """The declared environments: main's copy, or the working copy until it lands."""
    if main_text is None:
        if working_text is None:
            raise SystemExit(f"::error::{PATH} is on neither {MAIN} nor this checkout")
        warn(f"::warning::{PATH} is not on {MAIN} yet — using this branch's copy")
        return _parse(working_text)
    declared = _parse(main_text)
    try:
        working = _parse(working_text) if working_text is not None else declared
    except (SystemExit, ValueError):
        working = None  # malformed on the branch: ignored like any other branch edit
    if working != declared:
        warn(
            f"::warning::this branch's {PATH} differs from {MAIN}'s and is IGNORED — "
            f"environments change by merging to main and running porth-install"
        )
    return declared


def _parse(text: str) -> dict:
    doc = json.loads(text)
    envs = doc.get("environments") if isinstance(doc, dict) else None
    if not isinstance(envs, dict) or not envs:
        raise SystemExit(f"::error::{PATH} declares no environments")
    others = [s for s, e in envs.items() if e.get("deploys_from") == OTHER_BRANCHES]
    if len(others) > 1:
        raise SystemExit(f"::error::{PATH}: only one environment may deploy from {OTHER_BRANCHES} ({others})")
    return envs


def slot_for_ref(envs: dict, ref: str) -> str:
    branch = ref.removeprefix("refs/heads/")
    for slot, env in envs.items():
        if env.get("deploys_from") == branch:
            return slot
    for slot, env in envs.items():
        if env.get("deploys_from") == OTHER_BRANCHES:
            return slot
    raise SystemExit(f"::error::no environment deploys from {branch} and none from {OTHER_BRANCHES}")


def resolve(envs: dict, ref: str, override: str = "", expected: str = "") -> dict[str, str]:
    slot = override or slot_for_ref(envs, ref)
    if slot not in envs:
        raise SystemExit(f"::error::{slot} is not a declared environment ({', '.join(envs)})")
    if expected and expected != slot:
        raise SystemExit(
            f"::error::the workflow resolved {expected} but {PATH} says {ref} deploys {slot} — "
            f"the workflow's ref rule and the declared environments disagree"
        )
    return {
        "ENVIRONMENT_SLOT": slot,
        "TENANT_API_HOSTS": "true" if envs[slot].get("tenant_api_hosts") else "false",
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("resolve")
    r.add_argument("--ref", required=True)
    r.add_argument("--slot", default="")
    r.add_argument("--expected", default="")
    sub.add_parser("list")
    sub.add_parser("tfvars")
    args = ap.parse_args(argv)

    working = Path(PATH).read_text() if Path(PATH).exists() else None
    envs = load(_git_show(MAIN), working, warn=lambda m: print(m, file=sys.stderr))

    if args.cmd == "resolve":
        for k, v in resolve(envs, args.ref, args.slot, args.expected).items():
            print(f"{k}={v}")
    elif args.cmd == "list":
        print(",".join(envs))
    else:
        print(json.dumps({"tenant_host_slots": [s for s, e in envs.items() if e.get("tenant_api_hosts")]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
