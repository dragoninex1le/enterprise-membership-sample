"""Put an API mapping key back into the path before the app routes on it.

The bearer and suppliers APIs are mapped under a key on the tenant API hosts
(``{tenant}.api.{slot}.{zone}/mcp``, ``.../suppliers/...``). The path the function is
given does not carry the key (a supplier session reaches the portal as ``/session``),
but the app's routes are written with it (``/mcp``, ``/suppliers/me``). Each mapped
API's ``$default`` stage declares its key as the stage variable ``mapping_key``
(template.yml); the browser API, mapped at the root, declares none.
"""

from __future__ import annotations


def with_key(path: str, key: str | None) -> str:
    """``/session`` under key ``suppliers`` is ``/suppliers/session``. Already keyed, or no key: unchanged."""
    key = (key or "").strip("/")
    if not key:
        return path
    prefix = f"/{key}"
    if path == prefix or path.startswith(prefix + "/"):
        return path
    rest = path if path.startswith("/") else f"/{path}"
    return prefix if rest == "/" else prefix + rest


class RestoreMappingKey:
    """Middleware, outermost: every other layer and every route sees the keyed path."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            stage = (scope.get("aws.event") or {}).get("stageVariables") or {}
            scope = {**scope, "path": with_key(scope["path"], stage.get("mapping_key"))}
        await self.app(scope, receive, send)
