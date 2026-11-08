"""Live proof of the supplier portal (supplier-proof.yml).

Plays SupplierLink: signs assertions for two suppliers' contacts with the slot's
simulator key, trades them for Porth delegated sessions at the portal, and uses those
sessions against the deployed app. No browser, no person, nothing mocked.

  S1  the session route refuses what it must: no assertion, a forged one, an unlinked buyer
  S2  a contact of supplier A gets a session holding only the supplier role's permissions,
      sees the buyer and their supplier, submits an invoice, and finds it among their own
  S3  a contact of supplier B, same buyer, cannot see supplier A's invoice
  S4  a SupplierLink role the buyer has not mapped gets no session
  S5  an assertion is single-use
  S6  a session is bound to the buyer's API host, and a buyer's assertion cannot be
      traded on another tenant's host
  S7  a supplier session is refused everywhere outside /suppliers (the accounts MCP service)
  S8  /suppliers without a token is a 401 before any authorizer runs
  S9  no Porth session token reached either function's log

Prerequisites, checked first, each failure naming its fix: the buyer account linked
(Supplier network page), its supplier-role mapping, the supplier role seeded, Porth's
operator enabling the supplierlink connector, and Porth's Terraform listing the portal's
role as a mint caller. Exits 1 at the first failure; never prints a token.

Environment: ENVIRONMENT_SLOT, API_APEX, TENANT, BUYER, NETWORK_ROLE (mapped), UNMAPPED_ROLE.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
#: What a supplier contact may do: the supplier role in deploy/sample-app/roles.json.
SUPPLIER_PERMISSIONS = json.loads((ROOT / "deploy" / "sample-app" / "roles.json").read_text())["roles"]["supplier"]

sys.path.insert(0, str(ROOT / "supplier_portal"))
from supplier_portal.assertion import issue  # noqa: E402

SLOT, APEX = os.environ["ENVIRONMENT_SLOT"], os.environ["API_APEX"]
TENANT, BUYER = os.environ["TENANT"], os.environ["BUYER"]
NETWORK_ROLE = os.environ.get("NETWORK_ROLE", "billing")
UNMAPPED_ROLE = os.environ.get("UNMAPPED_ROLE", "proof-unmapped-role")
HOST, ELSEWHERE = f"{TENANT}.api.{APEX}", f"api.{APEX}"
BEGAN_MS = int(time.time() * 1000)

FIX = {
    "buyer_not_linked": f"Link SupplierLink buyer account {BUYER} to {TENANT} (Tenant Admin > Supplier network).",
    "unmapped_role_claim": f"Map SupplierLink role '{NETWORK_ROLE}' to the supplier role in {TENANT}, and seed that role.",
    "connector_not_enabled": ("Porth operator: porth-install delegated-config put --environment dev "
                              f"--slot {SLOT} --connector supplierlink --enable --allowed-roles supplier --apply"),
    "role_exceeds_ceiling": "The mapped EMS role is outside the connector's --allowed-roles (Porth operator).",
    "envelope_invalid": (f"Porth's install Terraform: add role ems-supplier-portal-{SLOT} to "
                         "delegated_mint_caller_role_arns, and apply."),
    "porth_unavailable": f"Porth did not answer; read the ems-supplier-portal-{SLOT} log.",
}


def network_key():
    import boto3
    from cryptography.hazmat.primitives import serialization

    pem = boto3.client("ssm").get_parameter(
        Name=f"/ems/{SLOT}/suppliers/supplierlink/simulator-private-key", WithDecryption=True)["Parameter"]["Value"]
    return serialization.load_pem_private_key(pem.encode(), password=None)


KEY = None


def assertion(supplier: str, contact: str, role: str = NETWORK_ROLE, buyer: str = BUYER) -> str:
    now = int(time.time())
    return issue({"iss": "supplierlink", "aud": "ems-accounts", "sub": contact, "jti": uuid.uuid4().hex,
                  "iat": now, "exp": now + 180, "buyer": buyer, "supplier": supplier, "role": role},
                 private_key=KEY)


def call(method: str, host: str, path: str, *, bearer: str | None = None, body=None):
    req = urllib.request.Request(f"https://{host}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("content-type", "application/json")
    req.add_header("user-agent", "ems-supplier-proof")
    if bearer is not None:
        req.add_header("authorization", f"Bearer {bearer}")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as err:
        status, raw = err.code, err.read()
    try:
        return status, json.loads(raw or b"null")
    except json.JSONDecodeError:
        return status, {"raw": raw.decode(errors="replace")[:200]}


def session(signed: str, host: str = HOST):
    return call("POST", host, "/suppliers/session", body={"assertion": signed})


#: A Porth session token. Nothing this job prints may carry one: the repository is
#: public, so its Actions logs are too (a live token reached one on 2026-11-08).
_TOKEN = re.compile(r"prth_[A-Za-z0-9_-]+")


def redacted(detail: str) -> str:
    return _TOKEN.sub("prth_<redacted>", detail)


def ok(label: str, condition: bool, detail: str = "") -> None:
    detail = redacted(detail)
    print(("PASS " if condition else "FAIL ") + label + (f" — {detail}" if detail else ""))
    if not condition:
        sys.exit(1)


def fix_for(answer) -> str:
    code = str((answer or {}).get("error", ""))
    return FIX.get(code.split(":")[0], f"the portal answered {code!r}")


def main() -> None:
    global KEY
    KEY = network_key()
    print(f"supplier proof: buyer {BUYER} -> tenant {TENANT} on {HOST} (slot {SLOT})\n")

    status, granted = session(assertion("proof-sup-a", "contact-a"))
    ok("prerequisites: a mapped supplier contact gets a session", status == 200,
       "" if status == 200 else f"{status} {granted}. Fix: {fix_for(granted)}")
    token_a = granted["token"]

    # S1
    ok("S1 no assertion", session("")[0] == 422)
    forged = assertion("proof-sup-a", "contact-a")[:-6] + "AAAAAA"
    ok("S1 a forged assertion", session(forged) == (401, {"error": "assertion_rejected"}))
    ok("S1 an unlinked buyer", session(assertion("proof-sup-a", "contact-a", buyer=f"unlinked-{uuid.uuid4().hex[:6]}"))
       == (403, {"error": "buyer_not_linked"}))

    # S2
    status, me = call("GET", HOST, "/suppliers/me", bearer=token_a)
    ok("S2 the session names the buyer and the supplier", status == 200
       and (me.get("buyer_tenant"), me.get("supplier")) == (TENANT, "proof-sup-a"), f"{status} {me}")
    expected = set(SUPPLIER_PERMISSIONS)
    held = set(me.get("permissions", []))
    ok("S2 the session holds the supplier role's permissions and nothing else", held == expected,
       f"extra {sorted(held - expected)}, missing {sorted(expected - held)}. Fix: make {TENANT}'s supplier "
       f"role hold exactly {sorted(expected)} (Tenant Admin > Roles)" if held != expected else "")
    reference = f"PROOF-{uuid.uuid4().hex[:8]}"
    status, invoice = call("POST", HOST, "/suppliers/invoices", bearer=token_a,
                           body={"vendor_name": "Proof Supplies A", "amount": 123.45, "supplier_reference": reference})
    ok("S2 the supplier submits an invoice", status == 200 and invoice.get("supplier_id") == "proof-sup-a", f"{status} {invoice}")
    status, mine = call("GET", HOST, "/suppliers/invoices", bearer=token_a)
    ok("S2 it is among their own invoices", status == 200 and reference in {i.get("supplier_reference") for i in mine},
       f"{status}")

    # S3
    status, granted_b = session(assertion("proof-sup-b", "contact-b"))
    ok("S3 a second supplier's contact gets a session", status == 200,
       f"{status} session {granted_b.get('session_id')}" if status == 200 else f"{status} {granted_b}")
    token_b = granted_b["token"]
    ok("S3 they cannot open supplier A's invoice",
       call("GET", HOST, f"/suppliers/invoices/{invoice['bill_id']}", bearer=token_b)[0] == 404)
    status, theirs = call("GET", HOST, "/suppliers/invoices", bearer=token_b)
    ok("S3 nor see it listed", status == 200 and reference not in {i.get("supplier_reference") for i in theirs})

    # S4
    ok("S4 an unmapped SupplierLink role", session(assertion("proof-sup-a", "contact-c", role=UNMAPPED_ROLE))
       == (403, {"error": "unmapped_role_claim"}))

    # S5
    once = assertion("proof-sup-a", "contact-a")
    first, second = session(once), session(once)
    ok("S5 an assertion is single-use", first[0] == 200 and second == (409, {"error": "duplicate_reference"}),
       f"{first[0]} then {second}")

    # S6
    ok("S6 the session is refused on another tenant's host",
       call("GET", ELSEWHERE, "/suppliers/me", bearer=token_a)[0] in (401, 403))
    ok("S6 the assertion cannot be traded on another tenant's host",
       session(assertion("proof-sup-a", "contact-a"), host=ELSEWHERE) == (403, {"error": "other_tenants_host"}))

    # S7
    status, refused = call("POST", HOST, "/mcp", bearer=token_a, body={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    ok("S7 the accounts MCP service refuses a supplier session",
       (status, refused) == (403, {"detail": "delegated_principal_refused"}), f"{status} {refused}")

    # S8
    ok("S8 /suppliers without a token", call("GET", HOST, "/suppliers/me")[0] == 401)

    # S9
    import boto3

    time.sleep(10)
    logs, leaks = boto3.client("logs"), []
    for fn in (f"ems-supplier-portal-{SLOT}", f"ems-sample-app-{SLOT}"):
        found = logs.filter_log_events(logGroupName=f"/aws/lambda/{fn}", startTime=BEGAN_MS,
                                       filterPattern='"prth_"', limit=5).get("events", [])
        leaks += [fn] * len(found)
    ok("S9 no session token in either function's log", not leaks, f"found in {sorted(set(leaks))}")

    print("\nThe supplier portal holds. Revocation (porth-install delegated-session revoke) is not "
          "covered here: the session token must not leave this job, and this job does not hold "
          "Porth's operator role.")


if __name__ == "__main__":
    main()
