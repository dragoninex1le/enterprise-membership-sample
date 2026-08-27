import logging
import os
import re
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum
from porth_common.internal_plane import log_plane_identity
from .director import DirectorMiddleware, SampleAppDirector
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


def handler(event, context=None):
    log_plane_identity(SampleAppDirector.SERVICE_ID)
    return _asgi(event, context)
