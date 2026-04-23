from fastapi import FastAPI
from mangum import Mangum
from .middleware import PorthContextMiddleware
from .routers import dashboard, ar, ap, approvals

app = FastAPI(title="Porth Sample App")
app.add_middleware(PorthContextMiddleware)
app.include_router(dashboard.router)
app.include_router(ar.router)
app.include_router(ap.router)
app.include_router(approvals.router)

handler = Mangum(app, lifespan="off")
