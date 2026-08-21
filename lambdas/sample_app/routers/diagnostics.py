"""Proof that the tenant boundary is enforced by IAM, not by this code.

The first version of this endpoint reported whether the request could read its
own data and inferred the rest. That is not proof. A page that renders proves
the credentials work; it says nothing about what they are refused, and refusal
is the entire property under test.

So this asks four questions, and the interesting answers are the failures:

    who am I          sts:GetCallerIdentity through the request's own
                      credentials, which returns the assumed-role ARN. Not
                      inferred from an error message, not a phrase chosen by
                      the UI — the name, from the service that issued it.

    my own partition  must be ALLOWED, or the app is broken.

    someone else's    must be DENIED, or there is no boundary. THREE probes now,
                      for three different holes — PORTH-594 put the environment
                      in the key, so there is a second axis to get wrong and it
                      is worth probing rather than assuming.

No probe needs another tenant or another environment to exist, and none
writes anything. A denial is returned identically whether the partition is empty
or full, which is the point: IAM refuses on the KEY, before any data is
consulted.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends

from porth_common.protocols.cloud_clients import DOCUMENT_STORE, IDENTITY_BROKER

from ..dependencies import porth
from ..director import TABLE_NAME, SampleAppDirector

router = APIRouter(prefix="/sample/diagnostics", tags=["diagnostics"])

# NO require_permission, and that is deliberate — the one route in this app
# without one. It exists to explain why other routes fail, and a permission
# failure is one of the things it explains; gating it would make it unavailable
# in precisely the situation it is for. It is still behind the authorizer, and
# reports only the caller's own tenant and their own request's identity.

_ASSUMED_ROLE = re.compile(r"assumed-role/([^/\s]+)")
_DENIED = ("AccessDenied", "not authorized", "AccessDeniedException")


def _read(table, partition: str) -> tuple[bool, str]:
    """Attempt one read. Returns (allowed, detail)."""
    try:
        table.query(
            KeyConditionExpression="pk = :pk",
            ExpressionAttributeValues={":pk": partition},
            Limit=1,
        )
    except Exception as exc:  # noqa: BLE001 — a refusal is a result, not a fault
        message = str(exc)
        if any(marker in message for marker in _DENIED):
            return False, "refused by IAM"
        return False, message[:200]
    return True, "allowed"


@router.get("/identity")
def identity(director: SampleAppDirector = Depends(porth)) -> dict:
    tenant = director.tenant_id
    result: dict = {
        "tenant_id": tenant,
        "narrowed": director.credentials() is not None,
        "app_table": TABLE_NAME,
        "role": None,
        "probes": [],
        "isolated": False,
    }

    # Who the request actually is. Through the Director so it uses the same
    # narrowed credentials everything else does — a separate client built from
    # the ambient identity would answer confidently about the wrong principal.
    try:
        arn = director.client(IDENTITY_BROKER).get_caller_identity()["Arn"]
        match = _ASSUMED_ROLE.search(arn)
        result["role"] = match.group(1) if match else arn
    except Exception as exc:  # noqa: BLE001
        result["role"] = None
        result["role_error"] = str(exc)[:200]

    table = director.resource(DOCUMENT_STORE).Table(TABLE_NAME)

    # PORTH-594 — the probes take their partition from the REPOSITORY rather
    # than composing one here. This endpoint previously built `TENANT#{tenant}`
    # itself, and when the key gained its environment segment that literal
    # would have stopped matching: the "expected allow" probe would have flipped
    # to denied and this page would have reported the boundary as broken while
    # it was working perfectly. A prober with its own copy of the key format
    # tests its copy.
    repo = director.repository
    environment = repo.environment

    own_allowed, own_detail = _read(table, repo.partition)

    # A partition that is not this tenant's and belongs to nobody. Proves the
    # plain case: another tenant's rows are unreachable.
    other = f"ENV#{environment}#TENANT#__isolation_probe__"
    other_allowed, other_detail = _read(table, other)

    # The prefix-extension hole, specifically. A LeadingKeys pattern written
    # TENANT#${tenant}* rather than the exact key plus TENANT#${tenant}#* would
    # admit this, and 'acme' would reach 'acme-staging' — the fault PORTH-593
    # found in Porth's own policy. Denied here means the pattern is right.
    sibling = f"{repo.partition}-probe"
    sibling_allowed, sibling_detail = _read(table, sibling)

    # The axis PORTH-594 added. This tenant, another environment: the same
    # customer's data in a slot this session was not issued for. Before the key
    # carried the environment there was nothing here to probe — the fence lived
    # on a session tag, which is a real constraint but not one a key query can
    # demonstrate. Now it can be shown rather than argued.
    cross_env = f"ENV#__isolation_probe__#TENANT#{tenant}"
    cross_env_allowed, cross_env_detail = _read(table, cross_env)

    result["environment"] = environment
    result["probes"] = [
        {"partition": repo.partition, "expect": "allow",
         "allowed": own_allowed, "detail": own_detail, "pass": own_allowed},
        {"partition": other, "expect": "deny",
         "allowed": other_allowed, "detail": other_detail, "pass": not other_allowed},
        {"partition": sibling, "expect": "deny",
         "allowed": sibling_allowed, "detail": sibling_detail, "pass": not sibling_allowed},
        {"partition": cross_env, "expect": "deny",
         "allowed": cross_env_allowed, "detail": cross_env_detail, "pass": not cross_env_allowed},
    ]
    # Isolation is all four, not the first. Reading your own data proves the
    # credentials work; only the refusals prove anything is being kept out.
    result["isolated"] = all(p["pass"] for p in result["probes"])
    return result
