import os
import re
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum
from .middleware import PorthContextMiddleware
from .routers import dashboard, ar, ap, approvals

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
# error responses (e.g. 401) from inner middleware.  If PorthContextMiddleware were
# outermost it would return a 401 without CORS headers and the browser would block it.
app.add_middleware(PorthContextMiddleware)   # added first → innermost

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

handler = Mangum(app, lifespan="off")
