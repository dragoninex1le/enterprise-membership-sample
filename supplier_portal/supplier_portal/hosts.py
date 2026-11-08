"""The tenant an API host serves, and CORS for the admin screen's calls to it.

Tenant API hosts are ``{tenant}.api.{slot}.{zone}`` (the platform tenant: ``api.{slot}.{zone}``)
and each serves exactly one UI origin, ``https://{tenant}.{slot}.{zone}``. The admin
screen calls the link routes across that origin with its session cookie, so the
answer allows credentials and names only that host's own UI — never another tenant's.
``CLOUDFRONT_ALIAS`` (``*.{slot}.{zone}``) gives the slot's base.
"""

from __future__ import annotations

import os


def _slot_base() -> str:
    alias = os.environ.get("CLOUDFRONT_ALIAS", "")
    return alias[2:].lower() if alias.startswith("*.") else ""


def tenant_on(host: str) -> str | None:
    base, name = _slot_base(), (host or "").split(":")[0].strip().lower()
    if not base:
        return None
    if name == f"api.{base}":
        return "platform"
    head, _, rest = name.partition(".")
    return head if rest == f"api.{base}" and head else None


def own_ui(host: str) -> str | None:
    tenant, base = tenant_on(host), _slot_base()
    if tenant is None:
        return None
    return f"https://{base}" if tenant == "platform" else f"https://{tenant}.{base}"


class OwnUiCors:
    """Pure ASGI, for /sample/suppliers/* only."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not scope.get("path", "").startswith("/sample/suppliers"):
            return await self.app(scope, receive, send)
        hdrs = {k.lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        origin, allowed = hdrs.get(b"origin", ""), own_ui(hdrs.get(b"host", ""))
        grant = [(b"access-control-allow-origin", origin.encode()), (b"access-control-allow-credentials", b"true"),
                 (b"vary", b"Origin")] if origin and origin == allowed else []

        if scope.get("method") == "OPTIONS":
            extra = [(b"access-control-allow-methods", b"GET,PUT,DELETE"),
                     (b"access-control-allow-headers", b"Content-Type,X-CSRF-Token,X-Porth-Environment"),
                     (b"access-control-max-age", b"600")] if grant else []
            await send({"type": "http.response.start", "status": 204 if grant else 403, "headers": grant + extra})
            return await send({"type": "http.response.body", "body": b""})

        async def add(message):
            if message["type"] == "http.response.start" and grant:
                message = {**message, "headers": [*(message.get("headers") or []), *grant]}
            await send(message)

        return await self.app(scope, receive, add)
