"""Debug tracing for the sample app (a copy of supplier_portal/supplier_portal/trace.py): one line per decision, ``key=value``.

Every line carries ``rid=`` — API Gateway's request id, the same value Porth's
authorizers log as ``request_id`` — so one request is followed through the
authorizer and this function by filtering both log groups on it.

``request.in`` / ``request.out`` are INFO, so every request leaves a line even when
DEBUG is off. Everything else is DEBUG (``SAMPLE_APP_LOG_LEVEL``).

NEVER logged: the assertion, any token, cookie values, the CSRF header's value, the
authorizer's credentials, the persisted Porth context. What is logged instead is
their *shape* (present, length, names) — enough to tell "missing" from "wrong".
"""

from __future__ import annotations

import contextvars
import json
import logging
import time
from typing import Any

log = logging.getLogger("sample_app.trace")

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("sample_app_rid", default="-")


def set_request(request_id: str | None) -> None:
    _request_id.set(request_id or "-")


def event(name: str, level: int = logging.DEBUG, **fields: Any) -> None:
    if not log.isEnabledFor(level):
        return
    rendered = " ".join(f"{k}={_value(v)}" for k, v in fields.items())
    log.log(level, "%s rid=%s %s", name, _request_id.get(), rendered)


def _value(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, (list, tuple, set)):
        return ",".join(str(x) for x in v) or "[]"
    text = str(v)
    return json.dumps(text) if (not text or any(c.isspace() for c in text)) else text


def authorization_shape(value: str | None) -> str:
    """``none`` | ``bearer-empty`` | ``bearer-prth(len=N)`` | ``bearer-jwt(len=N)`` | ``other``."""
    if not value:
        return "none"
    scheme, _, credential = value.partition(" ")
    if scheme.lower() != "bearer":
        return "other"
    credential = credential.strip()
    if not credential:
        return "bearer-empty"
    kind = "prth" if credential.startswith("prth_") else "jwt" if credential.count(".") == 2 else "opaque"
    return f"bearer-{kind}(len={len(credential)})"


def cookie_names(cookies: list[str] | None) -> list[str]:
    return sorted({c.split("=", 1)[0].strip() for c in cookies or [] if c})


#: Authorizer-context values safe to log. Everything else there (credentials among it)
#: is logged by key name only.
CONTEXT_SHOWN = ("tenant_id", "environment", "auth_source", "connector_type", "is_platform_admin")


class RequestTrace:
    """Middleware: one ``request.in`` and one ``request.out`` line for every request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        lambda_event = scope.get("aws.event") or {}
        context = lambda_event.get("requestContext") or {}
        headers = {k.lower(): v for k, v in (lambda_event.get("headers") or {}).items()}
        authorizer = (context.get("authorizer") or {}).get("lambda") or {}
        set_request(context.get("requestId"))
        event(
            "request.in", logging.INFO,
            method=scope["method"], route=lambda_event.get("routeKey"),
            raw_path=lambda_event.get("rawPath"), path=scope["path"],
            mapping_key=(lambda_event.get("stageVariables") or {}).get("mapping_key"),
            host=headers.get("host"), origin=headers.get("origin"),
            authorization=authorization_shape(headers.get("authorization")),
            cookies=cookie_names(lambda_event.get("cookies")),
            csrf_header="x-csrf-token" in headers,
            authorizer_keys=sorted(authorizer),
            **{k: authorizer.get(k) for k in CONTEXT_SHOWN if k in authorizer},
        )

        started = time.monotonic()
        status = None

        async def send_noting_status(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_noting_status)
        except Exception:
            event("request.crashed", logging.ERROR, ms=round((time.monotonic() - started) * 1000, 1))
            raise
        event("request.out", logging.INFO, status=status, ms=round((time.monotonic() - started) * 1000, 1))
