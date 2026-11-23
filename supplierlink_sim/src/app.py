"""SupplierLink simulator API.

SupplierLink is the made-up supplier network EMS's supplier portal trusts, the way
Elegans trusts NewStore. The SupplierLink sign-in page (EMS frontend, /supplierlink)
calls this API:

  POST /login   1. signs a SupplierLink login (an ES256 assertion) with the slot's key
                2. posts it to EMS:  POST https://{tenant}.api.{apex}/suppliers/session
                   (EMS checks it and asks Porth's delegated mint for a token)
                3. returns what EMS answered and how long EMS took

  GET  /docs    the API's own page; /openapi.json imports into Postman.

A FastAPI app behind Mangum, like EMS's other services. The private key never leaves
this function. EMS is not changed by it.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from mangum import Mangum
from pydantic import BaseModel

SLOT = os.environ.get("ENVIRONMENT_SLOT", "")
API_APEX = os.environ.get("API_APEX", "")  # e.g. porth-dau.ems.estynsoftware.cloud
KEY_PARAMETER = f"/ems/{SLOT}/suppliers/supplierlink/simulator-private-key"
ISSUER = "supplierlink"
AUDIENCE = "ems-accounts"
LOGIN_LIFETIME_SECONDS = 180

_private_key = None


class SignIn(BaseModel):
    """Who is signing in, and what SupplierLink says about them: a role, or permissions."""

    tenant: str = ""
    buyer: str = ""
    supplier: str = ""
    contact: str = ""
    method: Literal["role", "permissions"] = "role"
    role: str = ""
    permissions: str = ""  # comma-separated, as typed on the page


class SignInResult(BaseModel):
    session_url: str
    status: int  # EMS's HTTP status for POST /suppliers/session
    ems_ms: int  # how long EMS took to answer
    answer: Any  # EMS's answer: token, session_id, expires_at, api_base_url, or an error code


app = FastAPI(title="SupplierLink simulator")


@app.post("/login")
def login(form: SignIn) -> SignInResult:
    """Sign a SupplierLink login, trade it at EMS, and report EMS's answer."""
    tenant = required(form.tenant, "tenant")
    assertion = sign(claims(form))
    url = f"https://{tenant}.api.{API_APEX}/suppliers/session"

    started = time.perf_counter()
    status, answer = post(url, {"assertion": assertion})
    ems_ms = round((time.perf_counter() - started) * 1000)

    print(json.dumps({"event": "supplierlink_sim.login", "tenant": tenant, "status": status,
                      "ems_ms": ems_ms, "error": answer.get("error") if isinstance(answer, dict) else None}))
    return SignInResult(session_url=url, status=status, ems_ms=ems_ms, answer=answer)


handler = Mangum(app, lifespan="off")


def claims(form: SignIn) -> dict:
    """What SupplierLink says about the person signing in: by role or by permissions."""
    now = int(time.time())
    said = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": required(form.contact, "contact"),
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + LOGIN_LIFETIME_SECONDS,
        "buyer": required(form.buyer, "buyer"),
        "supplier": required(form.supplier, "supplier"),
    }
    if form.method == "permissions":
        permissions = [p.strip() for p in form.permissions.split(",") if p.strip()]
        if not permissions:
            raise HTTPException(400, "permissions is empty")
        said["permissions"] = permissions
    else:
        said["role"] = required(form.role, "role")
    return said


def sign(payload: dict) -> str:
    """An ES256 JWT, the format the supplier portal checks."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    header = {"alg": "ES256", "typ": "JWT"}
    signing_input = (f"{b64(json.dumps(header, separators=(',', ':')).encode())}."
                     f"{b64(json.dumps(payload, separators=(',', ':'), sort_keys=True).encode())}")
    r, s = decode_dss_signature(private_key().sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
    return f"{signing_input}.{b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


def private_key():
    """The slot's SupplierLink signing key, read from Parameter Store once per container."""
    global _private_key
    if _private_key is None:
        import boto3
        from cryptography.hazmat.primitives import serialization

        pem = boto3.client("ssm").get_parameter(Name=KEY_PARAMETER, WithDecryption=True)["Parameter"]["Value"]
        _private_key = serialization.load_pem_private_key(pem.encode(), password=None)
    return _private_key


def post(url: str, body: dict) -> tuple[int, object]:
    request = urllib.request.Request(url, method="POST", data=json.dumps(body).encode(),
                                     headers={"content-type": "application/json",
                                              "user-agent": "supplierlink-sim"})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as refused:
        status, raw = refused.code, refused.read()
    try:
        return status, json.loads(raw or b"null")
    except json.JSONDecodeError:
        return status, {"raw": raw.decode(errors="replace")[:500]}


def required(value: str, field: str) -> str:
    """A field the login cannot be signed without. Refused before anything is signed or sent."""
    if not value.strip():
        raise HTTPException(400, f"{field} is required")
    return value.strip()


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
