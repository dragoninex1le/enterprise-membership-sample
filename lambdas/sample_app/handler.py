import logging
import os
import re
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum
from .director import DirectorMiddleware
from .routers import dashboard, ar, ap, approvals, diagnostics

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
app.add_middleware(DirectorMiddleware)       # added first → innermost

app.add_middleware(                          # added last  → outermost
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=_origin_regex,
    allow_credentials=_allow_credentials,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)
app.include_router(dashboard.router)
app.include_router(ar.router)
app.include_router(ap.router)
app.include_router(approvals.router)
# PORTH-586: which role served the request. Behind the same authorizer as
# every other route, so it reports the identity of a REAL request rather
# than of a probe taking a different path to get here.
app.include_router(diagnostics.router)

handler = Mangum(app, lifespan="off")
