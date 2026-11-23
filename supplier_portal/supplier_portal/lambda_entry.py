"""Lambda entry for the supplier portal function. The app has nothing to start, so no lifespan."""

from mangum import Mangum

from supplier_portal.web import build

handler = Mangum(build(), lifespan="off")
