import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum
from .middleware import PorthContextMiddleware
from .routers import dashboard, ar, ap, approvals

app = FastAPI(title="Porth Sample App")

# Allow the CloudFront-hosted frontend to call this API.
# The list is narrowed to known origins; VITE_PLATFORM_APEX is the
# CloudFront subdomain prefix set at build time (e.g. "porth-sample").
_cf_alias = os.environ.get("CLOUDFRONT_ALIAS", "")
_allowed_origins = [f"https://{_cf_alias}"] if _cf_alias else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)

app.add_middleware(PorthContextMiddleware)
app.include_router(dashboard.router)
app.include_router(ar.router)
app.include_router(ap.router)
app.include_router(approvals.router)

handler = Mangum(app, lifespan="off")
