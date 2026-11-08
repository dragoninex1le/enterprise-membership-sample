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
import re
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


#: PORTH-655's browser handle: base64url of an HMAC-SHA256, 43 characters, no padding.
_HANDLE = re.compile(r"[A-Za-z0-9_-]{43}")


def authorization_shape(value: str | None) -> str:
    """``none`` | ``bearer-empty`` | ``bearer-handle(len=43)`` | ``bearer-prth(len=N)`` |
    ``bearer-jwt(len=N)`` | ``bearer-opaque(len=N)`` | ``other``."""
    if not value:
        return "none"
    scheme, _, credential = value.partition(" ")
    if scheme.lower() != "bearer":
        return "other"
    credential = credential.strip()
    if not credential:
        return "bearer-empty"
    kind = ("prth" if credential.startswith("prth_") else "jwt" if credential.count(".") == 2
            else "handle" if _HANDLE.fullmatch(credential) else "opaque")
    return f"bearer-{kind}(len={len(credential)})"


def cookie_names(cookies: list[str] | None) -> list[str]:
    return sorted({c.split("=", 1)[0].strip() for c in cookies or [] if c})
