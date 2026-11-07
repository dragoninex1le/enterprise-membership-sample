"""Reading a SupplierLink assertion — EMS's half of the trust.

Porth does not check who the supplier is; EMS does, here, before asking Porth for
anything. SupplierLink signs with its private key (ES256: ECDSA P-256, SHA-256) and
EMS checks with the public key it was given. EMS cannot produce an assertion, so a
leak of anything EMS holds cannot be turned into a supplier session.

An assertion is a compact JWS:

    header  {"alg": "ES256", "typ": "JWT", "kid": "<optional>"}
    claims  {"iss": "supplierlink", "aud": "ems-accounts",
             "sub":      the contact's id at SupplierLink (opaque),
             "jti":      unique per assertion,
             "iat", "exp": exp - iat <= 300,
             "buyer":    the SupplierLink buyer account the invoice is for,
             "supplier": the supplier's id at SupplierLink,
             "role":     the contact's role, as SupplierLink names it}
"""

from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, encode_dss_signature

from supplier_portal import CONNECTOR

ISSUER = "supplierlink"
AUDIENCE = "ems-accounts"
LONGEST = 300
CLOCK_SLACK = 10
_TOKEN_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")


class Unverified(Exception):
    """Not a SupplierLink assertion EMS will act on. ``why`` is for the log only."""

    def __init__(self, why: str) -> None:
        super().__init__(why)
        self.why = why


@dataclass(frozen=True)
class SupplierContact:
    contact: str
    supplier: str
    buyer: str
    role: str
    assertion_id: str
    checked_at: int
    valid_until: int

    @property
    def connector(self) -> str:
        return CONNECTOR


def _unb64(text: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError) as exc:
        raise Unverified("encoding") from exc


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def load_public_key(pem: str) -> ec.EllipticCurvePublicKey:
    key = serialization.load_pem_public_key(pem.encode())
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError("SupplierLink's key must be an EC P-256 public key")
    return key


def check(assertion: str, *, public_key: ec.EllipticCurvePublicKey, now: float | None = None) -> SupplierContact:
    pieces = (assertion or "").split(".")
    if len(pieces) != 3:
        raise Unverified("shape")
    head_txt, body_txt, sig_txt = pieces
    try:
        head, body = json.loads(_unb64(head_txt)), json.loads(_unb64(body_txt))
    except json.JSONDecodeError as exc:
        raise Unverified("json") from exc
    if not isinstance(head, dict) or not isinstance(body, dict):
        raise Unverified("json")
    if head.get("alg") != "ES256":
        raise Unverified("algorithm")

    raw_sig = _unb64(sig_txt)
    if len(raw_sig) != 64:
        raise Unverified("signature_length")
    der = encode_dss_signature(int.from_bytes(raw_sig[:32], "big"), int.from_bytes(raw_sig[32:], "big"))
    try:
        public_key.verify(der, f"{head_txt}.{body_txt}".encode(), ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        raise Unverified("signature") from exc

    clock = time.time() if now is None else now
    iat, exp = body.get("iat"), body.get("exp")
    if not isinstance(iat, int) or not isinstance(exp, int):
        raise Unverified("times")
    if exp + CLOCK_SLACK < clock:
        raise Unverified("expired")
    if iat - CLOCK_SLACK > clock:
        raise Unverified("from_the_future")
    if exp - iat > LONGEST:
        raise Unverified("too_long_lived")
    if body.get("iss") != ISSUER:
        raise Unverified("issuer")
    if body.get("aud") != AUDIENCE:
        raise Unverified("audience")

    fields = {}
    for name in ("sub", "jti", "buyer", "supplier", "role"):
        value = body.get(name)
        if not isinstance(value, str) or not _TOKEN_SAFE.match(value.strip() or "-"):
            raise Unverified(f"claim_{name}")
        fields[name] = value.strip()
    if "@" in fields["sub"]:
        # Porth keeps the external id pseudonymous; an email is not.
        raise Unverified("claim_sub_not_opaque")

    return SupplierContact(
        contact=fields["sub"], supplier=fields["supplier"], buyer=fields["buyer"], role=fields["role"],
        assertion_id=fields["jti"], checked_at=int(clock), valid_until=exp,
    )


def issue(claims: dict, *, private_key: ec.EllipticCurvePrivateKey, kid: str | None = None) -> str:
    """SupplierLink's side, for the tests and the live proof, which play the network.
    EMS never calls this: it holds no private key."""
    head = {"alg": "ES256", "typ": "JWT", **({"kid": kid} if kid else {})}
    signing_input = f"{_b64(json.dumps(head, separators=(',', ':')).encode())}." \
                    f"{_b64(json.dumps(claims, separators=(',', ':'), sort_keys=True).encode())}"
    r, s = decode_dss_signature(private_key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
    return f"{signing_input}.{_b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
