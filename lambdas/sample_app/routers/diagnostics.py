"""Which credentials served this request — the question PORTH-585 exists to answer.

Not a health check. The session-policy index decides which IAM role the
authorizer assumes for a request, and that decision is invisible from outside:
a page that renders and a page served under the wrong role look identical until
something is denied. This endpoint makes the answer visible in the UI.

It reports the ROLE the request is running as, and it gets it the only honest
way — by using the credentials rather than describing them. A read against this
app's own table either succeeds, in which case the request holds this app's
role, or it fails with an AccessDeniedException that names the role it actually
holds:

    User: assumed-role/porth-tenant-dev/porth-tenant is not authorized to
    perform: dynamodb:Query on table/porth-sample-app-dev

Both outcomes are informative and neither can be faked by the app. Before
PORTH-586 the second is exactly what this would have returned, because the
catch-all binding handed every request Porth's tenant role.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends

from porth_common.protocols.cloud_clients import DOCUMENT_STORE

from ..dependencies import porth
from ..director import TABLE_NAME, SampleAppDirector

router = APIRouter(prefix="/sample/diagnostics", tags=["diagnostics"])

# NO require_permission, and that is deliberate — the one route in this app
# without one.
#
# This exists to explain why other routes fail, and a permission failure is one
# of the things it explains. Gating it behind a permission would make it
# unavailable in precisely the situation it is for, and the symptom would be a
# diagnostic that 403s while the page it was meant to diagnose also 403s, with
# nothing to distinguish the two.
#
# It is still behind the authorizer like everything else, so it discloses
# nothing to an anonymous caller, and it reports only the caller's OWN tenant
# and the role serving their OWN request.

#: The role is the interesting half of an assumed-role ARN, and the session
#: name is not — it is per-request noise. Matched rather than split so a message
#: in an unexpected shape yields nothing instead of a wrong answer.
_ASSUMED_ROLE = re.compile(r"assumed-role/([^/\s]+)")


@router.get("/identity")
def identity(director: SampleAppDirector = Depends(porth)) -> dict:
    """What this request is running as, and whether it can reach this app's data.

    ``narrowed`` distinguishes the two ways of holding no tenant scope at all:
    credentials that were never issued (the authorizer degraded, or none ran)
    from credentials that were issued and are simply not this app's.
    """
    result: dict = {
        "tenant_id": director.tenant_id,
        "narrowed": director.credentials() is not None,
        "app_table": TABLE_NAME,
        "role": None,
        "app_table_reachable": False,
        "detail": "",
    }

    try:
        # Deliberately the REQUEST's credentials, not the ambient ones the
        # repository still uses (PORTH-616). The repository answers "can the
        # page render"; this answers "under whose authority", and only the
        # narrowed connection can.
        table = director.resource(DOCUMENT_STORE).Table(TABLE_NAME)
        table.query(
            KeyConditionExpression="pk = :pk",
            ExpressionAttributeValues={":pk": f"TENANT#{director.tenant_id}"},
            Limit=1,
        )
    except Exception as exc:  # noqa: BLE001 — the failure IS the answer here
        message = str(exc)
        match = _ASSUMED_ROLE.search(message)
        result["role"] = match.group(1) if match else None
        result["detail"] = message[:400]
        return result

    result["app_table_reachable"] = True
    result["detail"] = "the request's own credentials reached this app's table"
    return result
