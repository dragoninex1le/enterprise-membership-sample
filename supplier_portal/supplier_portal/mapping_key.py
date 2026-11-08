"""Put an API mapping key back into the path before the app routes on it.

The bearer and suppliers APIs are mapped under a key on the tenant API hosts
(``{tenant}.api.{slot}.{zone}/mcp``, ``.../suppliers/...``). API Gateway routes on the
path WITHOUT the key, and — as the live probes of porth-dau showed (a supplier
session reached the portal as ``/session``) — the path the function is given does
not carry it either. The app's routes are written with the key (``/mcp``,
``/suppliers/me``), so it is restored here, once, from the stage that served the
request: each mapped API's ``$default`` stage declares its key as the stage variable
``mapping_key`` (template.yml).

Idempotent: a path that already starts with the key is left alone, so it is right
whichever way API Gateway behaves. Events with no ``mapping_key`` (the browser API,
mapped at the root) pass through untouched.
"""

from __future__ import annotations

import copy


def restore_mapping_key(event: dict) -> dict:
    key = ((event.get("stageVariables") or {}).get("mapping_key") or "").strip("/")
    if not key:
        return event
    prefix = f"/{key}"

    def keyed(path):
        if path is None:
            return None
        if path == prefix or path.startswith(prefix + "/"):
            return path
        rest = path if path.startswith("/") else f"/{path}"
        return prefix if rest == "/" else prefix + rest

    http = (event.get("requestContext") or {}).get("http") or {}
    raw, routed = event.get("rawPath"), http.get("path")
    if keyed(raw) == raw and keyed(routed) == routed:
        return event
    out = copy.deepcopy(event)
    if raw is not None:
        out["rawPath"] = keyed(raw)
    if routed is not None:
        out["requestContext"]["http"]["path"] = keyed(routed)
    return out
