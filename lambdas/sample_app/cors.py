"""PORTH-656 — CORS on a tenant API host is bound to that host's own UI.

On a tenant-API-host slot the page is ``https://acme.{slot}.{zone}`` and this
API answers on ``acme.api.{slot}.{zone}`` (``api.{slot}.{zone}`` for the platform
tenant), with credentials. The session cookie there is host-only, so a page on
another tenant's origin that could read these responses would be reading acme's
data with acme's cookie.

``CORSMiddleware``'s origin regex allows every tenant UI of the slot, which is
right for the shared-host shape and too wide here. So, outermost: when the
request's Host is an API host and its ``Origin`` is not that host's UI, the
Origin header is dropped before ``CORSMiddleware`` sees it. No CORS headers are
written, and the browser refuses the response.

Every other host is passed through untouched.
"""
from __future__ import annotations

import os


def own_ui_origin(host: str, alias: str | None = None) -> str | None:
    """The UI origin an API host serves, or None if *host* is not an API host.

    ``alias`` is the slot's CloudFront wildcard (``*.{slot}.{zone}``), so the
    slot's base is ``{slot}.{zone}``:

        acme.api.{base}  ->  https://acme.{base}
        api.{base}       ->  https://{base}
    """
    alias = os.environ.get("CLOUDFRONT_ALIAS", "") if alias is None else alias
    if not alias.startswith("*."):
        return None
    base = alias[2:].lower()
    host = (host or "").strip().lower().split(":", 1)[0]
    if host == f"api.{base}":
        return f"https://{base}"
    suffix = f".api.{base}"
    if host.endswith(suffix):
        tenant = host[: -len(suffix)]
        if tenant and "." not in tenant:
            return f"https://{tenant}.{base}"
    return None


class HostBoundOriginMiddleware:
    """Pure ASGI; see the module docstring."""

    def __init__(self, app, alias: str | None = None):
        self.app = app
        self.alias = alias

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            headers = scope.get("headers") or []
            host = origin = None
            for k, v in headers:
                if k == b"host":
                    host = v.decode("latin-1")
                elif k == b"origin":
                    origin = v.decode("latin-1")
            expected = own_ui_origin(host or "", self.alias)
            if expected is not None and origin is not None and origin != expected:
                scope = dict(scope)
                scope["headers"] = [(k, v) for k, v in headers if k != b"origin"]
        await self.app(scope, receive, send)
