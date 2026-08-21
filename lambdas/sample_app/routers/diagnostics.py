"""Proof that the tenant boundary is enforced by IAM, not by this code.

The first version of this endpoint reported whether the request could read its
own data and inferred the rest. That is not proof. A page that renders proves
the credentials work; it says nothing about what they are refused, and refusal
is the entire property under test.

So this asks three questions, and the interesting answers are the failures:

    who am I          sts:GetCallerIdentity through the request's own
                      credentials, which returns the assumed-role ARN. Not
                      inferred from an error message, not a phrase chosen by
                      the UI — the name, from the service that issued it.

    my own partition  must be ALLOWED, or the app is broken.

    someone else's    must be DENIED, or there is no boundary. Two probes, for
                      two different holes.

Neither probe needs another tenant to exist, and neither writes anything. A
denial is returned identically whether the partition is empty or full, which is
the point: IAM refuses on the KEY, before any data is consulted.
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

    own_allowed, own_detail = _read(table, f"TENANT#{tenant}")

    # A partition that is not this tenant's and belongs to nobody. Proves the
    # plain case: another tenant's rows are unreachable.
    other_allowed, other_detail = _read(table, "TENANT#__isolation_probe__")

    # The prefix-extension hole, specifically. A LeadingKeys pattern written
    # TENANT#${tenant}* rather than the exact key plus TENANT#${tenant}#* would
    # admit this, and 'acme' would reach 'acme-staging' — the fault PORTH-593
    # found in Porth's own policy. Denied here means the pattern is right.
    sibling_allowed, sibling_detail = _read(table, f"TENANT#{tenant}-probe")

    result["probes"] = [
        {"partition": f"TENANT#{tenant}", "expect": "allow",
         "allowed": own_allowed, "detail": own_detail, "pass": own_allowed},
        {"partition": "TENANT#__isolation_probe__", "expect": "deny",
         "allowed": other_allowed, "detail": other_detail, "pass": not other_allowed},
        {"partition": f"TENANT#{tenant}-probe", "expect": "deny",
         "allowed": sibling_allowed, "detail": sibling_detail, "pass": not sibling_allowed},
    ]
    # Isolation is all three, not the first. Reading your own data proves the
    # credentials work; only the refusals prove anything is being kept out.
    result["isolated"] = all(p["pass"] for p in result["probes"])
    return result
