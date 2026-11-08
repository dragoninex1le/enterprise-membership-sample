import logging
import os
import re
import time
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum
from porth_common.internal_plane import log_plane_identity
from .cors import HostBoundOriginMiddleware
from .director import DirectorMiddleware, SampleAppDirector
from .mapping_key import restore_mapping_key
from . import trace
from .routers import dashboard, ar, ap, approvals, diagnostics, suppliers
from .accounts_mcp import http as accounts_mcp

# PORTH-622 — set once, for the whole package, at the entry point.
#
# Nothing did this before, so every module logger inherited Lambda's root
# default of WARNING and every log.info in this app was discarded. It was
# invisible precisely because it looks like nothing: the app worked, the logs
# were empty, and an empty log group reads as "quiet" rather than "muted".
#
# What it cost: `sample_app.fingerprint` never appeared on the SYNCHRONOUS path
# either, so the round trip we witnessed in PORTH-599 was only ever observable
# from ffug's side. When PORTH-622 came to assert one trace_id across all four
# hops, three could be shown and the initiating one could not — not because it
# had not happened, but because it had never been able to say so.
#
# On the package logger rather than the root: this app's lines become visible
# without also turning on every library's DEBUG chatter.
logging.getLogger("sample_app").setLevel(
    os.environ.get("SAMPLE_APP_LOG_LEVEL", "INFO")
)

# PORTH-623 — the LIBRARY's logger, separately.
#
# Setting this module's own level does nothing for porth_common: loggers are
# per-package, so the lines that say which key signed and which key verified
# stay silent at Lambda's WARNING default no matter how loud this service is.
#
# That is the same trap that muted this whole app for four stories — an empty
# log group reading as quiet rather than silenced — one package over, and it
# would have been found the same way: by needing a line and not having it.
#
# Own variable, because library detail and application detail are different
# questions. Turning up porth_common brings key resolution, trust-document cache
# ages and per-candidate verification; you want that while diagnosing a
# signature, and not otherwise.
logging.getLogger("porth_common").setLevel(
    os.environ.get("PORTH_COMMON_LOG_LEVEL", "INFO")
)


app = FastAPI(title="Porth Sample App")

# Allow the CloudFront-hosted frontend to call this API.
# CLOUDFRONT_ALIAS may be a wildcard subdomain pattern (e.g. "*.example.com").
# Starlette's CORSMiddleware does exact string matching on allow_origins — it
# does NOT expand wildcard subdomains. Use allow_origin_regex instead so that
# every tenant subdomain (e.g. demo-tenant.porth-sample.*.cloud) is allowed.
_cf_alias = os.environ.get("CLOUDFRONT_ALIAS", "")
if _cf_alias.startswith("*."):
    # Convert "*.foo.bar" → regex matching "https://<subdomain>.foo.bar"
    # The optional group also matches the bare apex (no subdomain prefix).
    _base = re.escape(_cf_alias[2:])
    _origin_regex = rf"https://([^.]+\.)?{_base}"
    _allowed_origins: list[str] = []
    _allow_credentials = True
elif _cf_alias:
    _origin_regex = rf"https://{re.escape(_cf_alias)}"
    _allowed_origins = []
    _allow_credentials = True
else:
    # No alias configured — open to all origins (dev fallback only).
    # allow_credentials must be False when allow_origins=["*"].
    _origin_regex = None
    _allowed_origins = ["*"]
    _allow_credentials = False

# Middleware is applied LIFO — last added = outermost = first to process requests.
# CORSMiddleware must be outermost so it wraps ALL responses, including early-exit
# error responses (e.g. 401) from inner middleware.  If DirectorMiddleware were
# outermost it would return a 401 without CORS headers and the browser would block it.
# PORTH-613 — the shared Director, not a hand-rolled context. Still innermost,
# so CORSMiddleware wraps even the early 401/403 responses; a refusal without
# CORS headers is one the browser hides from the app entirely.


class SupplierBoundary:
    """A delegated caller — a supplier's contact holding a Porth session the supplier
    portal obtained for them (``auth_source == "exchange"``) — is served by
    /suppliers/* and nothing else. Porth says who the caller is and how they were
    vouched for; which routes that is enough for is this app's decision, and a
    supplier does not read the buyer's ledgers, approve, administer, or drive the
    accounts MCP service.

    Innermost, so the Director is attached when it runs. A route added later is
    closed to suppliers without anyone having to remember to close it.
    """

    REFUSAL = b'{"detail":"delegated_principal_refused"}'

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and not scope.get("path", "").startswith("/suppliers/"):
            director = (scope.get("state") or {}).get("director")
            if director is not None and suppliers.delegated(director):
                trace.event("boundary.refused", logging.INFO, path=scope.get("path"),
                            reason="delegated_principal_outside_suppliers",
                            connector=suppliers.delegated(director).get("connector_type"))
                await send({"type": "http.response.start", "status": 403, "headers": [
                    (b"content-type", b"application/json"), (b"content-length", str(len(self.REFUSAL)).encode())]})
                await send({"type": "http.response.body", "body": self.REFUSAL})
                return
        await self.app(scope, receive, send)


app.add_middleware(SupplierBoundary)          # added first → innermost (the Director is set by then)
app.add_middleware(DirectorMiddleware)

app.add_middleware(                          # added last  → outermost
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=_origin_regex,
    allow_credentials=_allow_credentials,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    # PORTH-656: X-CSRF-Token and X-Porth-Environment as well. Same-origin
    # through CloudFront they were never preflighted; from a tenant UI to its
    # API host they are, and a header missing here fails every write.
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Porth-Environment"],
    max_age=600,
)

# PORTH-656 — outermost of all: on an API host, only that host's own UI origin
# reaches CORSMiddleware. See cors.py.
app.add_middleware(HostBoundOriginMiddleware)
app.include_router(dashboard.router)
app.include_router(ar.router)
app.include_router(ap.router)
app.include_router(approvals.router)
# PORTH-586: which role served the request. Behind the same authorizer as
# every other route, so it reports the identity of a REAL request rather
# than of a probe taking a different path to get here.
app.include_router(diagnostics.router)
# The accounts MCP service, at /mcp. Reached only through the app's bearer API
# (template.yml SampleAppBearerApi); the browser API serves /sample/* alone.
app.include_router(accounts_mcp.router)
# The supplier portal's routes for suppliers' contacts, through the SUPPLIERS API
# (template.yml SampleAppSuppliersApi). See routers/suppliers.py.
app.include_router(suppliers.router)

# PORTH-623 — say who this deployable is and where it will read, once, on the
# first invocation. INFO on purpose: this is the post-deploy check, and putting
# it behind DEBUG would mean only someone who already suspects a problem can
# see the answer.
#
# It resolves nothing and reads nothing, so it costs one line and cannot fail
# in a way that matters. A wrong PORTH_BRANCH shows up here as a wrong path
# rather than three layers down as a refusal.
#
# Wrapped rather than called at import: the log level is configured in this
# module, and a line emitted during import races that. `log_plane_identity` is
# once-per-process itself, so the wrapper stays a no-op after the first call.
_asgi = Mangum(app, lifespan="off")


#: Authorizer-context values safe to log. Everything else there (credentials
#: among it) is logged by key name only.
_CONTEXT_SHOWN = ("tenant_id", "environment", "auth_source", "connector_type", "is_platform_admin")


def handler(event, context=None):
    log_plane_identity(SampleAppDirector.SERVICE_ID)
    rc = event.get("requestContext") or {}
    http = rc.get("http") or {}
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    authorizer = (rc.get("authorizer") or {}).get("lambda") or {}
    trace.set_request(rc.get("requestId"))

    # The bearer and suppliers APIs deliver key-stripped paths; see mapping_key.py.
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
        response = _asgi(restored, context)
    except Exception:
        trace.event("request.crashed", logging.ERROR, ms=round((time.monotonic() - started) * 1000, 1))
        raise
    trace.event("request.out", logging.INFO, status=(response or {}).get("statusCode"),
                ms=round((time.monotonic() - started) * 1000, 1))
    return response
