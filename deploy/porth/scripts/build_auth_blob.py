#!/usr/bin/env python3
"""Build the /porth/auth configuration blob from the testbed manifest.

Lifted out of porth-install.yml (PORTH-598). It used to live inside a
``python3 -c '...'`` in the workflow, which made it a single-quoted shell string
containing Python containing JSON — three levels of quoting in one place. That
is not a style preference: an apostrophe in a *comment* inside that block ended
the shell string and broke the deploy (PORTH-589), and the error surfaced as a
bash syntax error pointing at a parenthesis.

Reads its inputs from the environment so the workflow stays declarative:

    MANIFEST                the /porth/config/testbed value (JSON)
    PORTH_DNS_ZONE          e.g. ems.estynsoftware.cloud
    PORTH_DOMAIN            the proxy's own host
    PORTH_SPA_ORIGINS_RAW   legacy origin list
    EFF_FIXED_ENVIRONMENT   the ADR-Z8 slot
    PORTH_SESSIONS_TABLE
    PORTH_SESSION_KMS

Writes the blob as JSON on stdout. Anything diagnostic goes to stderr, so the
caller can capture stdout directly.

What it deliberately does NOT write: root_url, environments and tenant_origins.
Those are policy.MANAGED_KEYS, owned by `porth-install auth-config`, which runs
after this. Writing them here is what PORTH-587/588 removed.
"""
from __future__ import annotations

import json
import os
import sys


def build(manifest: dict, env: dict) -> dict:
    idp = (manifest.get("platform") or {}).get("idp") or {}

    missing = [k for k in ("issuer", "jwks_uri") if not idp.get(k)]
    if missing:
        raise SystemExit(
            f"::error::platform.idp is missing {missing} (PORTH-488 needs both)"
        )

    zone = env.get("PORTH_DNS_ZONE", "").rstrip(".")
    if not zone:
        raise SystemExit("::error::PORTH_DNS_ZONE is empty — the cookie domain derives from it")

    blob = {
        # Identity, from the manifest verbatim. `client_id` becomes
        # interactive_client_id because that is the name the proxy reads.
        "issuer": idp["issuer"],
        "jwks_uri": idp["jwks_uri"],
        "interactive_client_id": idp.get("client_id", ""),
        "audience": idp.get("audience", ""),
        "protocol": idp.get("protocol", "oidc"),
        # Stack shape, derived by the pipeline.
        "custom_domain": env.get("PORTH_DOMAIN", ""),
        "cookie_domain": f".{zone}",
        "dns_zone": zone,
        "spa_origins": env.get("PORTH_SPA_ORIGINS_RAW", ""),
        "platform_tenant_id": "platform",
        "environment": env.get("EFF_FIXED_ENVIRONMENT", ""),
        "sessions_table": env.get("PORTH_SESSIONS_TABLE", ""),
        "session_kms_key_id": env.get("PORTH_SESSION_KMS", ""),
    }

    # Providers without RP-initiated logout simply omit it.
    if idp.get("end_session_endpoint"):
        blob["end_session_endpoint"] = idp["end_session_endpoint"]

    return blob


def main() -> int:
    raw = os.environ.get("MANIFEST", "").strip()
    if not raw:
        raise SystemExit(
            "::error::MANIFEST is empty — /porth/config/testbed holds the platform IdP config"
        )

    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"::error::/porth/config/testbed is not valid JSON: {exc}") from exc

    blob = build(manifest, os.environ)
    print(f"issuer {blob['issuer']}", file=sys.stderr)
    print(json.dumps(blob))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
