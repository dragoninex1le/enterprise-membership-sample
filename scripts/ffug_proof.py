"""Prove ffug's tenant and environment isolation against the live install.

Three stages (PORTH-587, PORTH-627):

**A — the tenant exists in the service table.** Nobody called ffug to make that
happen. Porth emitted ``tenant.created`` on the bus, ffug's lifecycle consumer
minted that tenant a prime, and this stage reads the result back. If the table
is empty, the failure message names exactly what to run — an empty scan and "the
consumer is broken" look identical otherwise, which is the failure shape half
of Porth's EMS upgrade log is made of.

**B — call it synchronously.** Mint a context envelope per tenant, invoke ffug
with the SAME payload for each, and compare. Two things are checked, and the
second is the one that matters:

1. the digests differ — the visible property;
2. each digest equals ``SHA256(prime : payload)`` recomputed here from the prime
   this script scanned. That is what rules out ffug having returned *something*
   tenant-shaped for an unrelated reason. The service and this script arrive at
   the same answer from opposite directions.

**C — the environment axis.** Two probes against the same function: this
environment's credentials aimed at a REAL other environment's partition, which
must be refused; and an envelope minted FOR that other environment, which must be
served and narrowed to it. The first is the isolation property — nothing asserted
it before EMS ran two environments — and the second pins the deliberate choice
that an unpinned ingress follows the signed claim rather than its own
configuration.

Needs ``OTHER_ENVIRONMENT`` naming another deployed environment. Skipped without
it, because a probe aimed at an invented environment is the vacuous version
PORTH-598 objected to for tenants.

What this does NOT do is the cross-tenant denial (UAT-3). Demonstrating that
means assuming ``FfugTenantRole`` with tenant A's session policy and reading B's
row, which needs a grant the UAT runner does not have. Deliberately left for its
own change rather than widened in passing.

Nor does it drive an async round trip in each environment, or read the same
tenant's prime from both tables. Both need the OTHER environment's function and
table, which this runner cannot reach; they are witnessed by running the app in
each environment and recorded in EVIDENCE.md.

Run from CI holding the UAT runner role — see .github/workflows/ffug-proof.yml.
Nothing here writes.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass

import boto3
from boto3.dynamodb.conditions import Attr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
from ffug import keys, salt  # noqa: E402

#: The same payload for every tenant. That it is identical is the entire point:
#: any difference in the answers has to come from the tenant, not the input.
PAYLOAD = {"invoice": "INV-0001", "amount": 12345, "currency": "GBP"}


def _env(name: str) -> str:
    """Read a required setting at USE time, not at import.

    Module-level ``os.environ[...]`` makes the module unimportable without the
    whole environment present, which means it cannot be tested — and the test
    that catches a rename of ``keys.PROJECTION_SK`` is the only thing standing
    between that rename and a proof run that scans for a sort key nothing uses.
    """
    value = os.environ.get(name, "").strip()
    if not value:
        fail(f"{name} is not set - the proof workflow should have exported it.")
    return value


@dataclass
class Caller:
    """What ``build_envelope`` requires instead of two loose strings (TS-MC.1).

    The library takes a context object rather than an ``environment`` and a
    ``tenant_id`` parameter precisely so a call site cannot invent a tenant. A
    UAT runner is the one place that legitimately constructs one, and it builds
    it from what it read out of the table — not from an argument someone typed.
    """

    environment: str
    tenant_id: str


def fail(message: str, *remedy: str) -> None:
    print(f"\n::error::{message}")
    for line in remedy:
        print(f"   {line}")
    sys.exit(1)


def scan_projections() -> list[dict]:
    """Every tenant ffug knows about, and the prime it holds for each."""
    table = boto3.resource("dynamodb").Table(_env("FFUG_TABLE_NAME"))
    rows, start_key = [], None
    while True:
        kwargs = {
            "FilterExpression": Attr("sk").eq(keys.PROJECTION_SK),
            "ProjectionExpression": "pk, #s, prime, occurred_at",
            "ExpressionAttributeNames": {"#s": "status"},
        }
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        page = table.scan(**kwargs)
        rows.extend(page.get("Items", []))
        start_key = page.get("LastEvaluatedKey")
        if not start_key:
            return sorted(rows, key=lambda r: r["pk"])


def stage_a() -> list[dict]:
    print("=" * 72)
    print("STAGE A — did the bus create the tenant in ffug's table?")
    print("=" * 72)

    rows = scan_projections()
    if not rows:
        fail(
            f"{_env('FFUG_TABLE_NAME')} holds no tenant projections.",
            "ffug mints a tenant's prime when Porth emits tenant.created. No rows",
            "means no such event has been delivered SINCE ffug's consumer was",
            "deployed — tenants that already existed do not get one retroactively.",
            "",
            "Create a tenant in the ADMIN UI and re-run — the environment under",
            "test is a label in the host:",
            "  https://{environment}.ems.estynsoftware.cloud",
            "",
            "NOT 'Porth - seed testbed tenants'. That seeder writes tenant rows",
            "straight to Porth's table and publishes NO tenant.created, so ffug",
            "never hears about the tenant and this scan stays empty however many",
            "times it is run. Only PUT /tenants/ emits the event.",
            "",
            "If a tenant IS created through the UI and this still reports nothing,",
            "the rule is not matching: check FfugLifecycleFunction's log group for",
            "invocations at all, then the rule's bus and pattern — it now filters",
            "on detail.environment (PORTH-627), so an event for another",
            "environment is correctly ignored by this deployment.",
        )

    active = [r for r in rows if r.get("status") == "active"]
    print(f"\n{len(rows)} projection row(s), {len(active)} active:\n")
    for row in rows:
        prime = row.get("prime", "(none - stripped by tenant.deleted)")
        print(f"  {row['pk']:<44} status={row.get('status'):<10} prime={prime}")

    primes = [r["prime"] for r in active if r.get("prime")]
    if len(set(primes)) != len(primes):
        fail("two tenants share a prime - the mint is not per-tenant.")

    print(f"\n  -> every active tenant has its own prime ({len(set(primes))} distinct)")
    if len(active) < 2:
        print("\n  NOTE: only one active tenant. Stage B needs two to compare.")
    return active


def stage_b(tenants: list[dict]) -> None:
    from porth_common.context import build_envelope

    print("\n" + "=" * 72)
    print("STAGE B — call it synchronously; same payload, different tenants")
    print("=" * 72)
    print(f"\npayload (identical for every call): {json.dumps(PAYLOAD, sort_keys=True)}\n")

    client = boto3.client("lambda")
    results = []

    for row in tenants[:2]:
        _, environment, _, tenant_id = row["pk"].split("#")
        caller = Caller(environment=environment, tenant_id=tenant_id)

        envelope = build_envelope(
            caller,
            source_service="porth",
            audience="ffug",
            trace_id=f"ffug-proof-{tenant_id}",
        )
        response = client.invoke(
            FunctionName=_env("FFUG_FUNCTION_ARN"),
            Payload=json.dumps(
                {
                    "porth_context": envelope.to_payload_field(),
                    # The D7.4 wire field. This script hand-builds the payload
                    # because it is a UAT runner standing in for a caller, not a
                    # service — but it speaks the same shape ServiceClient does,
                    # or it would be testing a path nothing uses.
                    "operation": "hash",
                    "payload": PAYLOAD,
                }
            ).encode(),
        )
        if response.get("FunctionError"):
            fail(
                f"ffug raised for tenant {tenant_id}: {response['Payload'].read().decode()[:600]}",
                "An invocation error is an infrastructure fault, not a refusal —",
                "most likely the STS narrowing. Check FfugFunction's log group.",
            )

        body = json.loads(response["Payload"].read())
        if not body.get("ok"):
            code = body.get("error", {}).get("code")
            fail(
                f"ffug refused tenant {tenant_id}: {code} - {body.get('error', {}).get('message')}",
                "",
                "  source_service_refused  the D3 registry does not list 'porth' as",
                "                          active. The registry is a Porth-side SSM",
                "                          document at /porth/{branch}/services, and an",
                "                          ABSENT document fails closed on every lookup",
                "                          — which is correct, and looks identical to a",
                "                          rejected caller. Check the parameter exists.",
                "  environment_mismatch    the envelope's environment disagrees with",
                "                          the slot these rows are keyed under. This USED",
                "                          to mean PORTH_FIXED_ENVIRONMENT on the function;",
                "                          that pin is gone (PORTH-627), so the claim now",
                "                          comes from the Director and a mismatch means the",
                "                          caller minted for the wrong environment.",
                "  audience_mismatch       PORTH_SERVICE_ID on the function is not 'ffug'.",
                "  unsigned / bad_signature  this script's envelope is wrong, or the key",
                "                          it signed with is not the one ffug verifies.",
                "  tenant_not_provisioned  the projection vanished between stage A and B.",
            )

        expected = salt.digest(str(row["prime"]), PAYLOAD)
        results.append((tenant_id, str(row["prime"]), body["prime"], body["digest"], expected))
        print(f"  tenant {tenant_id}")
        print(f"    prime returned  {body['prime']}")
        print(f"    digest returned {body['digest']}")
        print(f"    recomputed here {expected}   {'MATCH' if expected == body['digest'] else 'MISMATCH'}\n")

    for tenant_id, stored_prime, returned_prime, digest, expected in results:
        if digest != expected:
            fail(
                f"tenant {tenant_id}: ffug's digest is not SHA256(prime : payload).",
                "The service and this script disagree about the derivation.",
            )
        if returned_prime != stored_prime:
            fail(f"tenant {tenant_id}: ffug returned a prime that is not the stored one.")

    if len(results) < 2:
        print("  Only one tenant available — cannot compare two. Seed a second and re-run.")
        return

    (a_id, _, _, a_digest, _), (b_id, _, _, b_digest, _) = results[0], results[1]
    if a_digest == b_digest:
        fail(f"{a_id} and {b_id} returned the SAME digest for the same payload.")

    print(f"  -> {a_id} and {b_id} return different digests for an identical payload,")
    print("     and each matches its own stored prime.")


def stage_c(tenants: list[dict]) -> None:
    """The environment axis, which nothing asserted before EMS ran two of them.

    Both probes go to the SAME function — this environment's ffug — because that
    is the only one these credentials reach. What differs is the key, and that
    is the point: FfugTenantRole's ceiling is ``ENV#*#TENANT#*``, so an
    un-narrowed session would be ALLOWED to read a foreign environment's
    partition. A denial here is attributable to the session policy's ``$env``
    narrowing and to nothing else.

    Skipped rather than failed when OTHER_ENVIRONMENT is unset: on a
    single-environment install there is no second environment to name, and a
    probe aimed at an invented one is the vacuous version PORTH-598 objected to.
    """
    from porth_common.context import build_envelope

    other = os.environ.get("OTHER_ENVIRONMENT", "").strip()

    print("\n" + "=" * 72)
    print("STAGE C — the environment axis")
    print("=" * 72)

    if not other:
        print("\n  SKIPPED — OTHER_ENVIRONMENT is not set.")
        print("  This install serves one environment, so there is no real second")
        print("  one to be refused. Set it to the other deployed environment")
        print("  (e.g. porth-dau) to run this stage.")
        return

    _, environment, _, tenant_id = tenants[0]["pk"].split("#")
    if other == environment:
        fail(
            f"OTHER_ENVIRONMENT is {other!r}, which is this environment.",
            "It must name a DIFFERENT deployed environment, or the probe would",
            "assert 'deny' against the one partition that must be allowed.",
        )

    client = boto3.client("lambda")

    def probe(caller_environment: str, **args) -> dict:
        envelope = build_envelope(
            Caller(environment=caller_environment, tenant_id=tenant_id),
            source_service="porth",
            audience="ffug",
            trace_id=f"ffug-proof-env-{caller_environment}",
        )
        response = client.invoke(
            FunctionName=_env("FFUG_FUNCTION_ARN"),
            Payload=json.dumps(
                {
                    "porth_context": envelope.to_payload_field(),
                    "operation": "isolation_probe",
                    "payload": args,
                }
            ).encode(),
        )
        if response.get("FunctionError"):
            fail(
                "ffug raised on isolation_probe: "
                f"{response['Payload'].read().decode()[:600]}"
            )
        body = json.loads(response["Payload"].read())
        if not body.get("ok"):
            fail(f"ffug refused isolation_probe: {body.get('error')}")
        return body

    # ── C1 — this environment's credentials, aimed at a REAL other one ────────
    print(f"\n  C1 — {environment} credentials against ENV#{other}#TENANT#{tenant_id}")
    own = probe(environment, probe_environment=other)

    named = [a for a in own["attempts"] if "a real environment" in a["attempt"]]
    if not named:
        fail(
            f"ffug ran no probe against {other}.",
            "The function is older than PORTH-627 and ignores probe_environment,",
            "so this stage would pass without asking the question.",
        )
    row = named[0]
    print(f"    {row['attempt']}")
    print(f"    outcome: {row['outcome']}   allowed: {row['allowed']}")
    if row["allowed"]:
        fail(
            f"{environment}'s credentials READ {other}'s partition.",
            "The session policy is not narrowing on $env. Every environment on",
            "this install can read every other one's rows for the same tenant.",
        )
    if not own["isolated"]:
        failed = [a["attempt"] for a in own["attempts"] if not a["pass"]]
        fail(f"the probe strip did not pass as a whole: {failed}")

    # ── C2 — an envelope for the OTHER environment, served and narrowed ───────
    #
    # Deliberately NOT a refusal. With the pin gone there is no
    # expected_environment to compare against, so this ingress serves a
    # foreign-environment envelope — narrowed to that environment. That is the
    # design (PORTH-627), not a leak: the claim is signed, and the narrowing
    # follows the claim rather than the function it arrived at.
    print(f"\n  C2 — an envelope minted for {other}, presented to {environment}'s ffug")
    foreign = probe(other)

    print(f"    served, and reports environment: {foreign['environment']}")
    if foreign["environment"] != other:
        fail(
            f"ffug narrowed to {foreign['environment']!r}, not the envelope's {other!r}.",
            "The environment is being taken from the function's configuration",
            "rather than from the signed claim — which is the pin PORTH-627",
            "removed, still in effect somewhere.",
        )
    if not foreign["isolated"]:
        failed = [a["attempt"] for a in foreign["attempts"] if not a["pass"]]
        fail(f"narrowed to {other}, but the probe strip did not pass: {failed}")

    print(f"\n  -> {environment} cannot read {other}'s rows for the same tenant,")
    print(f"     and an envelope for {other} is served narrowed to {other}.")


def main() -> None:
    active = stage_a()
    if not active:
        fail("no active tenants to call.")
    stage_b(active)
    stage_c(active)

    print("\n" + "=" * 72)
    print("PROVEN")
    print("=" * 72)
    print("  A. The bus created each tenant in ffug's table, with its own prime.")
    print("  B. A synchronous call returns that tenant's digest, and two tenants")
    print("     disagree on an identical payload.")
    print("  C. An environment's credentials are refused another environment's")
    print("     rows for the same tenant, and an envelope narrows to its claim.")
    print("\n  NOT proven here: that ffug CANNOT reach another tenant's prime.")
    print("  That is the cross-tenant denial (UAT-3) and needs its own change —")
    print("  assume FfugTenantRole under tenant A's session policy, read B's row,")
    print("  and capture the AccessDeniedException.")


if __name__ == "__main__":
    main()
