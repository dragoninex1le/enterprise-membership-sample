#!/usr/bin/env python3
"""Walk the deployed adapter through every permutation it is expected to answer (PRF-10).

Run locally, with credentials for the EMS account, against the live function:

    python3 infra/provisioning-adapter/scripts/permutations.py --profile <ems-profile>

Each case is one `aws lambda invoke`, so this exercises the deployed adapter exactly as a caller
would, including requests prawf itself would refuse to build (a malformed envelope, a foreign major
version). Read-only: `capabilities` reads the slot map and one tenants row; every other verb is
refused or unsupported before it touches data. Safe against a live slot.

What each case asserts:
  * the outcome and reason code the adapter's check order produces (handler.py):
      envelope -> contract version -> slot -> entity -> verb
  * the §9 invariants on every response: ok carries no reason code; a non-ok carries one from the
    closed list, no results, and a message saying why
  * on `capabilities`, the declaration itself: the served slot, contract 1.0.0, the one implemented
    verb, the eight catalogue entities with no verbs yet (C1)
  * if `prawf_schemas` is importable, every response against the canonical response schema

Exit status is 0 only when every case passes. --report writes each request and response as JSON.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

VERBS = ("bootstrap", "seed", "reset", "ensure", "absent", "teardown", "status")
ENTITIES = (
    "porth-platform", "porth-tenant", "porth-idp-config", "porth-claim-mapping",
    "porth-app-permission", "porth-role-grant", "porth-role", "porth-idp",
)
#: common.schema.json $defs/reasonCode - the closed list (§9).
REASON_CODES = {
    "environment_protected", "scope_violation", "dataset_conflict", "version_incompatible",
    "unknown_entity", "limit_exceeded", "not_implemented", "upstream_error", "timeout",
}
CONTRACT = "1.0.0"
UNKNOWN_ENTITY = "porth-tables"  # the contract's own example entity; EMS never declares it
OTHER_SLOT = "porth-sample"      # a real Porth slot this adapter does not serve


@dataclass
class Case:
    group: str
    name: str
    request: object
    outcome: str
    reason: str | None = None
    checks: list = field(default_factory=list)


def envelope(verb: str, entity: str | None = None, *, version: object = CONTRACT,
             slot: object = None, **extra) -> dict:
    req: dict = {"contract_version": version, "verb": verb}
    if verb != "capabilities":
        req["run"] = {"run_id": "permutations", "dry_run": True}
    if entity is not None:
        req["entity"] = entity
    if slot is not None:
        req["slot"] = slot
    req.update(extra)
    return req


def declares_the_target(slot: str):
    def check(resp: dict) -> list[str]:
        problems = []
        body = (resp.get("results") or [{}])[0]
        env = body.get("environment") or {}
        if env.get("slot") != slot:
            problems.append(f"environment.slot is {env.get('slot')!r}, expected {slot!r}")
        if body.get("contract_versions") != [CONTRACT]:
            problems.append(f"contract_versions is {body.get('contract_versions')!r}")
        if body.get("verbs") != ["capabilities"]:
            problems.append(f"verbs is {body.get('verbs')!r}, expected ['capabilities']")
        ids = [e.get("id") for e in body.get("entities", [])]
        if sorted(ids) != sorted(ENTITIES):
            problems.append(f"entities are {ids!r}")
        if any(e.get("verbs") for e in body.get("entities", [])):
            problems.append("an entity declares verbs, but none are implemented (C1)")
        if body.get("environment_class") not in ("disposable", "protected"):
            problems.append(f"environment_class is {body.get('environment_class')!r}")
        return problems
    return check


def answered_in(version: str):
    def check(resp: dict) -> list[str]:
        got = resp.get("contract_version")
        return [] if got == version else [f"answered in {got!r}, expected {version!r}"]
    return check


def cases(slot: str) -> list[Case]:
    target = declares_the_target(slot)
    out = [
        # 1. The envelope. Anything that is not one is refused: there is no shared version.
        Case("envelope", "a string, not an object", "hello", "refused", "version_incompatible"),
        Case("envelope", "a list, not an object", ["capabilities"], "refused", "version_incompatible"),
        Case("envelope", "no contract_version", {"verb": "capabilities"}, "refused", "version_incompatible"),
        Case("envelope", "no verb", {"contract_version": CONTRACT}, "refused", "version_incompatible"),

        # 2. Version negotiation (§10): same major, highest version no newer than the caller's.
        Case("version", "1.0.0", envelope("capabilities"), "ok", None, [target, answered_in(CONTRACT)]),
        Case("version", "1.0.5 is answered in 1.0.0", envelope("capabilities", version="1.0.5"),
             "ok", None, [answered_in(CONTRACT)]),
        Case("version", "1.1.0 is answered in 1.0.0", envelope("capabilities", version="1.1.0"),
             "ok", None, [answered_in(CONTRACT)]),
        Case("version", "2.0.0 has no common version", envelope("capabilities", version="2.0.0"),
             "refused", "version_incompatible"),
        Case("version", "0.9.0 has no common version", envelope("capabilities", version="0.9.0"),
             "refused", "version_incompatible"),
        Case("version", "'1.0' is not semver", envelope("capabilities", version="1.0"),
             "refused", "version_incompatible"),
        Case("version", "a number is not semver", envelope("capabilities", version=1),
             "refused", "version_incompatible"),

        # 3. The slot. 1.0.0 cannot send one (PRF-19 adds it); the adapter already resolves it.
        Case("slot", "omitted, one slot served", envelope("capabilities"), "ok", None, [target]),
        Case("slot", f"{slot}, the served slot", envelope("capabilities", slot=slot), "ok", None, [target]),
        Case("slot", f"{OTHER_SLOT}, not served", envelope("capabilities", slot=OTHER_SLOT),
             "refused", "scope_violation"),
        Case("slot", "'*', never a glob", envelope("capabilities", slot="*"), "refused", "scope_violation"),
        Case("slot", "a number", envelope("capabilities", slot=7), "refused", "scope_violation"),

        # 4. The check order: the stronger failure wins.
        Case("order", "a foreign version beats a bad slot and an unknown entity",
             envelope("seed", UNKNOWN_ENTITY, version="2.0.0", slot=OTHER_SLOT),
             "refused", "version_incompatible"),
        Case("order", "a bad slot beats an unknown entity",
             envelope("seed", UNKNOWN_ENTITY, slot=OTHER_SLOT), "refused", "scope_violation"),
        Case("order", "an unknown entity beats an unimplemented verb",
             envelope("seed", UNKNOWN_ENTITY), "refused", "unknown_entity"),
    ]

    # 5. Every verb against every entity. Nothing beyond capabilities is implemented yet, so a known
    #    entity is `unsupported` (prawf skips it), an unknown one is `refused`.
    for verb in VERBS + ("frobnicate",):
        out.append(Case(f"verb:{verb}", "no entity", envelope(verb), "unsupported", "not_implemented"))
        for entity in ENTITIES:
            out.append(Case(f"verb:{verb}", entity, envelope(verb, entity), "unsupported", "not_implemented"))
        out.append(Case(f"verb:{verb}", f"{UNKNOWN_ENTITY} (unknown)", envelope(verb, UNKNOWN_ENTITY),
                        "refused", "unknown_entity"))
    return out


def invoke(function: str, request: object, aws: list[str]) -> tuple[dict | None, str | None]:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "response.json"
        proc = subprocess.run(
            [*aws, "lambda", "invoke", "--function-name", function,
             "--cli-binary-format", "raw-in-base64-out", "--payload", json.dumps(request), str(out)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            return None, (proc.stderr.strip() or proc.stdout.strip())
        meta = json.loads(proc.stdout or "{}")
        body = out.read_text("utf-8")
        if meta.get("FunctionError"):
            return None, f"the adapter crashed ({meta['FunctionError']}): {body[:300]}"
        return json.loads(body), None


def invariants(resp: dict) -> list[str]:
    problems = []
    outcome, reason = resp.get("outcome"), resp.get("reason_code")
    if not resp.get("adapter_version"):
        problems.append("no adapter_version")
    if outcome == "ok":
        if reason is not None:
            problems.append(f"ok carries a reason code ({reason})")
    else:
        if reason not in REASON_CODES:
            problems.append(f"reason code {reason!r} is not in the closed list")
        if resp.get("results"):
            problems.append("a non-ok answer carries results")
        if not (resp.get("diagnostics") or {}).get("messages"):
            problems.append("a non-ok answer says nothing about why")
    return problems


def judge(c: Case, resp: dict, validate) -> list[str]:
    """Everything wrong with one answer. Empty means the case passed."""
    problems = []
    got = (resp.get("outcome"), resp.get("reason_code"))
    if got != (c.outcome, c.reason):
        want = c.outcome + (f"/{c.reason}" if c.reason else "")
        problems.append(f"expected {want}, got {got[0]}" + (f"/{got[1]}" if got[1] else ""))
    problems += invariants(resp)
    if validate:
        problems += validate(resp)
    if not problems:
        for check in c.checks:
            problems += check(resp)
    return problems


def schema_validator():
    try:
        from prawf_schemas import validate_contract_response  # type: ignore[import-not-found]
    except ImportError:
        return None

    def validate(resp: dict) -> list[str]:
        result = validate_contract_response(resp)
        return [] if result.valid else [f"schema: {e}" for e in result.errors]
    return validate


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--profile", help="AWS profile for the EMS account (default: the environment's)")
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--function", default="porth-provisioning-adapter")
    ap.add_argument("--slot", default="porth-dau", help="the slot the adapter serves")
    ap.add_argument("--only", help="run only cases whose group starts with this, e.g. version or verb:seed")
    ap.add_argument("--report", type=Path, help="write every request and response here as JSON")
    args = ap.parse_args()

    aws = ["aws", "--region", args.region, "--output", "json"]
    if args.profile:
        aws += ["--profile", args.profile]

    validate = schema_validator()
    if validate is None:
        print("note: prawf_schemas is not importable - responses are not checked against the schema\n")

    selected = [c for c in cases(args.slot) if not args.only or c.group.startswith(args.only)]
    report, failed = [], 0
    for c in selected:
        resp, error = invoke(args.function, c.request, aws)
        problems = [error] if error else judge(c, resp, validate)
        failed += bool(problems)
        mark = "FAIL" if problems else "pass"
        print(f"{mark}  {c.group:<17} {c.name}")
        for p in problems:
            print(f"        - {p}")
        report.append({"group": c.group, "name": c.name, "request": c.request, "response": resp,
                       "passed": not problems, "problems": problems})
        if error and "credentials" in error.lower():
            print("\nstopping: no usable AWS credentials for the EMS account")
            failed += len(selected) - len(report)
            break

    print(f"\n{len(selected) - failed} of {len(selected)} passed")
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n", "utf-8")
        print(f"report: {args.report}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
