"""ffug's per-tenant salt — a random prime, and the digest built from it.

The salt is minted once per tenant, by the lifecycle consumer, on the
``tenant.created`` event (PORTH-587). Nothing on the request path can mint one:
a caller that arrives before the bus event is refused rather than served under a
freshly-invented salt, for the same reason ``resolve_tenant_context`` never had a
fallback tenant.

**What the prime does and does not prove.** Two tenants sending an identical
payload get different digests, because their primes differ — that is the visible
property, and it is the one this fixture exists to show. It is *not* a secret:
it is stored in plaintext in a table the UAT runner can read, so anyone holding
that read can reproduce that tenant's digest. Tenant-unique, not
tenant-exclusive, and deliberately so (Richard, 2026-08-20).

The exclusivity claim lives one layer down and is not arithmetic at all: ffug
serving tenant A holds an STS session pinned by ``dynamodb:LeadingKeys`` to
``ENV#{env}#TENANT#A*``, so it cannot *read* B's prime and therefore cannot
compute B's digest. DynamoDB refuses the read; no branch in this file is
involved. State the claim that way round — a reader who thinks the prime is
doing the securing will draw the wrong conclusion from it.

Stored as a decimal STRING, not a Number. DynamoDB hands Numbers back as
``Decimal``, and a salt that arrives as ``Decimal('17')`` on one path and
``17`` on another hashes to two different digests. A string has one reading.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any

#: Wide enough that two tenants colliding is not a thing anyone need think
#: about, small enough to read off a table scan in a demo.
PRIME_BITS = 64

_SMALL_PRIMES = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)

#: With these twelve bases Miller-Rabin is DETERMINISTIC below
#: 3,317,044,064,679,887,385,961,981 — far above any 64-bit candidate. So this
#: is an exact primality test here, not a probabilistic one, and the function
#: needs no error term and no retry budget.
_WITNESSES = _SMALL_PRIMES


def is_prime(n: int) -> bool:
    """Exact primality for any n a 64-bit mint can produce."""
    if n < 2:
        return False
    for p in _SMALL_PRIMES:
        if n % p == 0:
            return n == p

    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1

    for a in _WITNESSES:
        x = pow(a, d, n)
        if x == 1 or x == n - 1:
            continue
        for _ in range(r - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


def mint_prime() -> str:
    """A fresh random prime for one tenant, as a decimal string.

    ``secrets``, not ``random``: the mint runs once per tenant and lives for the
    tenant's lifetime, so a predictable sequence would make every tenant's salt
    predictable from any other's. Cheap insurance on a value that is written
    once and read forever.
    """
    while True:
        # Top bit set so the prime is always full-width (a demo where one
        # tenant's salt is six digits and another's is twenty invites the
        # question of whether the short one is a bug), bottom bit set so even
        # candidates are never tested.
        candidate = secrets.randbits(PRIME_BITS) | (1 << (PRIME_BITS - 1)) | 1
        if is_prime(candidate):
            return str(candidate)


def canonical(payload: Any) -> str:
    """The exact bytes that get hashed.

    Sorted keys and no whitespace, so ``{"a":1,"b":2}`` and ``{"b":2,"a":1}``
    are the same payload and produce the same digest. Without this the digest
    would depend on dict ordering, and the isolation demo would show two
    different digests for the same tenant and be read as a leak.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def digest(prime: str, payload: Any) -> str:
    """``SHA256(prime : payload)`` — the tenant-scoped fingerprint of a payload.

    The separator matters. Concatenating ``prime`` and payload directly lets one
    (prime, payload) pair produce the same bytes as a different pair — the
    classic length-extension-adjacent ambiguity — and ``:`` cannot appear in a
    decimal prime, so the split point is unambiguous.
    """
    return hashlib.sha256(f"{prime}:{canonical(payload)}".encode("utf-8")).hexdigest()
