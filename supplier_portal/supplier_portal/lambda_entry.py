"""Lambda entry for the supplier portal function."""

from mangum import Mangum

from supplier_portal.mapping_key import restore_mapping_key
from supplier_portal.web import build

_adapter = Mangum(build(), lifespan="off")


def handler(event, context=None):
    # The suppliers API delivers /session for /suppliers/session; see mapping_key.py.
    return _adapter(restore_mapping_key(event), context)
