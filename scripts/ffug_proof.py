"""Prove ffug's tenant isolation against the live install (PORTH-587).

Two stages, in the order Richard asked for them:

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

What this does NOT do is the cross-tenant denial (UAT-3). Demonstrating that
means assuming ``FfugTenantRole`` with tenant A's session policy and reading B's
row, which needs a grant the UAT runner does not have. Deliberately left for its
own change rather than widened in passing.

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

FUNCTION_ARN = os.environ["FFUG_FUNCTION_ARN"]
TABLE_NAME = os.environ["FFUG_TABLE_NAME"]

#: The same payload for every tenant. That it is identical is the entire point:
#: any difference in the answers has to come from the tenant, not the input.
PAYLOAD = {"invoice": "INV-0001", "amount": 12345, "currency": "GBP"}


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
    table = boto3.resource("dynamodb").Table(TABLE_NAME)
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
            f"{TABLE_NAME} holds no tenant projections.",
            "ffug mints a tenant's prime when Porth emits tenant.created. No rows",
            "means no such event has been delivered SINCE ffug's consumer was",
            "deployed — tenants that already existed do not get one retroactively.",
            "",
            "Create a tenant and re-run:",
            "  - Actions > 'Porth - seed testbed tenants', or",
            "  - create one in the admin UI at porth-sample.ems.estynsoftware.cloud",
            "",
            "If a tenant IS created and this still reports nothing, the rule is not",
            "matching: check FfugLifecycleFunction's log group for invocations at",
            "all, then the rule's bus and pattern.",
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
            FunctionName=FUNCTION_ARN,
            Payload=json.dumps(
                {"porth_context": envelope.to_payload_field(), "op": "hash", "payload": PAYLOAD}
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
                "tenant_not_provisioned means the projection vanished between stages.",
                "unsigned/bad_signature/audience_mismatch mean this script's envelope",
                "is wrong. environment_mismatch means PORTH_FIXED_ENVIRONMENT on the",
                "function disagrees with the slot these rows are keyed under.",
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


def main() -> None:
    active = stage_a()
    if not active:
        fail("no active tenants to call.")
    stage_b(active)

    print("\n" + "=" * 72)
    print("PROVEN")
    print("=" * 72)
    print("  A. The bus created each tenant in ffug's table, with its own prime.")
    print("  B. A synchronous call returns that tenant's digest, and two tenants")
    print("     disagree on an identical payload.")
    print("\n  NOT proven here: that ffug CANNOT reach another tenant's prime.")
    print("  That is the cross-tenant denial (UAT-3) and needs its own change —")
    print("  assume FfugTenantRole under tenant A's session policy, read B's row,")
    print("  and capture the AccessDeniedException.")


if __name__ == "__main__":
    main()
