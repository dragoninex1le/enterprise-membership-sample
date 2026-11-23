"""SupplierLink sign-in simulator.

SupplierLink is the made-up supplier network EMS's supplier portal trusts, the way
Elegans trusts NewStore. This app plays SupplierLink so a person can click through a
supplier login:

  GET  /        a page with one form
  POST /login   1. signs a SupplierLink login (an ES256 assertion) with the slot's key
                2. posts it to EMS:  POST https://{tenant}.api.{apex}/suppliers/session
                   (EMS checks it and asks Porth's delegated mint for a token)
                3. returns what EMS answered and how long EMS took

EMS is not changed by this app and does not know it exists.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
import uuid

SLOT = os.environ.get("ENVIRONMENT_SLOT", "")
API_APEX = os.environ.get("API_APEX", "")  # e.g. porth-dau.ems.estynsoftware.cloud
KEY_PARAMETER = f"/ems/{SLOT}/suppliers/supplierlink/simulator-private-key"
ISSUER = "supplierlink"
AUDIENCE = "ems-accounts"
LOGIN_LIFETIME_SECONDS = 180

_private_key = None


def handler(event, context):
    method = event["requestContext"]["http"]["method"]
    path = event.get("rawPath", "/")

    if method == "GET" and path == "/":
        return {"statusCode": 200, "headers": {"content-type": "text/html; charset=utf-8"}, "body": page()}

    if method == "POST" and path == "/login":
        try:
            form = json.loads(request_body(event) or "{}")
            result = login(form)
        except ValueError as problem:
            result = {"error": str(problem)}
        return {"statusCode": 200, "headers": {"content-type": "application/json"}, "body": json.dumps(result)}

    return {"statusCode": 404, "body": "not found"}


def login(form: dict) -> dict:
    """Sign a SupplierLink login, trade it at EMS, and report EMS's answer."""
    tenant = required(form, "tenant")
    assertion = sign(claims(form))
    url = f"https://{tenant}.api.{API_APEX}/suppliers/session"

    started = time.perf_counter()
    status, answer = post(url, {"assertion": assertion})
    ems_ms = round((time.perf_counter() - started) * 1000)

    print(json.dumps({"event": "supplierlink_sim.login", "tenant": tenant, "status": status,
                      "ems_ms": ems_ms, "error": answer.get("error") if isinstance(answer, dict) else None}))
    return {"session_url": url, "status": status, "ems_ms": ems_ms, "answer": answer}


def claims(form: dict) -> dict:
    """What SupplierLink says about the person signing in: by role or by permissions."""
    now = int(time.time())
    said = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": required(form, "contact"),
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + LOGIN_LIFETIME_SECONDS,
        "buyer": required(form, "buyer"),
        "supplier": required(form, "supplier"),
    }
    if form.get("method") == "permissions":
        permissions = [p.strip() for p in str(form.get("permissions", "")).split(",") if p.strip()]
        if not permissions:
            raise ValueError("permissions is empty")
        said["permissions"] = permissions
    else:
        said["role"] = required(form, "role")
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


def required(form: dict, field: str) -> str:
    value = str(form.get(field, "")).strip()
    if not value:
        raise ValueError(f"{field} is required")
    return value


def request_body(event) -> str:
    body = event.get("body") or ""
    return base64.b64decode(body).decode() if event.get("isBase64Encoded") else body


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def page() -> str:
    return PAGE.replace("{slot}", SLOT)


# The page. Every control a test drives has a label (prawf finds controls by role and
# name) and a data-prawfid, which is how prawf builds this app's control manifest.
PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SupplierLink sign-in</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 640px; margin: 2rem auto; padding: 0 1rem; }
  label { display: block; margin: .6rem 0 .2rem; font-weight: 600; }
  input[type=text] { width: 100%; padding: .4rem; box-sizing: border-box; }
  fieldset { border: 1px solid #ccc; margin: .8rem 0; }
  button { margin-top: 1rem; padding: .6rem 1.2rem; font-size: 1rem; }
  pre { background: #f4f4f4; padding: .8rem; white-space: pre-wrap; word-break: break-all; }
</style>
</head>
<body>
<h1>SupplierLink sign-in</h1>
<p>Slot <strong>{slot}</strong>. Signs a supplier login as SupplierLink and trades it at EMS for a Porth token.</p>

<form id="signin" data-prawfid="signin.form">
  <label for="tenant">Buyer tenant</label>
  <input type="text" id="tenant" name="tenant" value="ems-test" data-prawfid="signin.form.tenant">

  <label for="buyer">SupplierLink buyer account</label>
  <input type="text" id="buyer" name="buyer" value="buyer-ems-test" data-prawfid="signin.form.buyer">

  <label for="supplier">Supplier</label>
  <input type="text" id="supplier" name="supplier" value="proof-sup-a" data-prawfid="signin.form.supplier">

  <label for="contact">Contact</label>
  <input type="text" id="contact" name="contact" value="contact-a" data-prawfid="signin.form.contact">

  <fieldset>
    <legend>What SupplierLink says about them</legend>
    <label><input type="radio" name="method" value="role" checked data-prawfid="signin.form.by-role"> By role</label>
    <label><input type="radio" name="method" value="permissions" data-prawfid="signin.form.by-permissions"> By permissions</label>

    <label for="role">SupplierLink role</label>
    <input type="text" id="role" name="role" value="billing" data-prawfid="signin.form.role">

    <label for="permissions">SupplierLink permissions (comma-separated)</label>
    <input type="text" id="permissions" name="permissions" value="invoices:submit, invoices:view"
           data-prawfid="signin.form.permissions">
  </fieldset>

  <button type="submit" data-prawfid="signin.form.sign-in">Sign in</button>
</form>

<h2>Result</h2>
<p>Status: <strong id="status" data-prawfid="signin.result.status">-</strong>
   &nbsp; EMS took: <strong id="ems-ms" data-prawfid="signin.result.ems-ms">-</strong> ms</p>
<h3>Token</h3>
<pre id="token" data-prawfid="signin.result.token">-</pre>
<h3>EMS answered</h3>
<pre id="answer" data-prawfid="signin.result.answer">-</pre>

<script>
document.getElementById("signin").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = Object.fromEntries(new FormData(e.target).entries());
  document.getElementById("status").textContent = "signing in...";
  document.getElementById("ems-ms").textContent = "-";
  document.getElementById("token").textContent = "-";
  document.getElementById("answer").textContent = "-";
  const reply = await fetch("login", {method: "POST", headers: {"content-type": "application/json"},
                                      body: JSON.stringify(form)});
  const result = await reply.json();
  document.getElementById("status").textContent = result.error ? "not sent: " + result.error : result.status;
  document.getElementById("ems-ms").textContent = result.ems_ms ?? "-";
  document.getElementById("token").textContent = (result.answer && result.answer.token) || "-";
  document.getElementById("answer").textContent = JSON.stringify(result.answer ?? result, null, 2);
});
</script>
</body>
</html>
"""
