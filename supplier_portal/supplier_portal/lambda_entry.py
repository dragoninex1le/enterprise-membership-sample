"""Lambda entry for the supplier portal function."""

from mangum import Mangum

from supplier_portal.web import build

_adapter = Mangum(build(), lifespan="off")


def handler(event, context=None):
    return _adapter(event, context)
