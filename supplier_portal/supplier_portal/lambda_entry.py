"""Lambda entry for the supplier portal function."""

import logging
import time

from mangum import Mangum

from supplier_portal import trace
from supplier_portal.mapping_key import restore_mapping_key
from supplier_portal.web import build

_adapter = Mangum(build(), lifespan="off")

#: Authorizer-context values safe to log. Everything else there (credentials
#: among it) is logged by key name only.
_CONTEXT_SHOWN = ("tenant_id", "environment", "auth_source", "connector_type", "is_platform_admin")


def handler(event, context=None):
    rc = event.get("requestContext") or {}
    http = rc.get("http") or {}
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    authorizer = (rc.get("authorizer") or {}).get("lambda") or {}
    trace.set_request(rc.get("requestId"))

    # The suppliers API delivers /session for /suppliers/session; see mapping_key.py.
    restored = restore_mapping_key(event)
    trace.event(
        "request.in", logging.INFO,
        method=http.get("method"), route=event.get("routeKey"),
        raw_path=event.get("rawPath"), path=restored.get("rawPath"),
        mapping_key=(event.get("stageVariables") or {}).get("mapping_key"),
        host=headers.get("host"), origin=headers.get("origin"),
        authorization=trace.authorization_shape(headers.get("authorization")),
        cookies=trace.cookie_names(event.get("cookies")),
        csrf_header="x-csrf-token" in headers,
        authorizer_keys=sorted(authorizer),
        **{k: authorizer.get(k) for k in _CONTEXT_SHOWN if k in authorizer},
    )
    started = time.monotonic()
    try:
        response = _adapter(restored, context)
    except Exception:
        trace.event("request.crashed", logging.ERROR, ms=round((time.monotonic() - started) * 1000, 1))
        raise
    trace.event("request.out", logging.INFO, status=(response or {}).get("statusCode"),
                ms=round((time.monotonic() - started) * 1000, 1))
    return response
