"""``GET /mcp/whoami``: how the bearer surface accepted this token.

Reached only through the app's bearer API (template.yml ``SampleAppBearerApi``,
mapped under ``mcp`` on the tenant API hosts), behind Porth's bearer authorizer.
The SPA's bearer-token test page calls it with a token from
``GET /porth/auth/token`` — or one pasted from an earlier session — to show
whether Porth still accepts that token. After the session that handed it out
signs out, Porth refuses it (``session_ended``) and this route is never reached.

It reports what the authorizer decided, from the context it put on the request:
the tenant, the slot, ``auth_source`` and ``session_bound``, who, and with which
roles and permissions. Never the credentials the context also carries.

No require_permission, like /sample/diagnostics/identity: it explains whether a
token works, so it must answer for any token Porth accepts.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from .. import trace

router = APIRouter(tags=["bearer"])

#: What may leave this route. An allowlist: the context also holds the request's
#: narrowed STS credentials, and a new context key must not reach a browser by
#: default.
SHOWN = (
    "tenant_id", "environment", "auth_source", "session_bound", "route_kind",
    "porth_user_id", "external_id", "user_email", "roles", "permissions",
)


@router.get("/mcp/whoami", include_in_schema=False)
def whoami(request: Request) -> dict:
    director = getattr(request.state, "director", None)
    context = getattr(director, "_raw_context", None) or {}
    if director is None or not context.get("tenant_id"):
        trace.event("bearer.refused", logging.INFO, reason="no_porth_context")
        raise HTTPException(401, "No Porth context on this request.")
    shown = {key: context[key] for key in SHOWN if key in context}
    trace.event("bearer.whoami", tenant=shown.get("tenant_id"), auth_source=shown.get("auth_source"),
                session_bound=shown.get("session_bound"))
    return shown
