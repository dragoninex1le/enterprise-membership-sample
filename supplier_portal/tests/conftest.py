import os
import pathlib
import sys

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# Pinned, not defaulted: the deploy workflow exports the slot's real CLOUDFRONT_ALIAS,
# and the tests' hosts are porth-dau's. With setdefault the suite passed on porth-dau
# and failed on porth-sample, where every test host became "another tenant's host".
os.environ["CLOUDFRONT_ALIAS"] = "*.porth-dau.ems.estynsoftware.cloud"
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")


@pytest.fixture(scope="session")
def network_key():
    """SupplierLink's key pair, as the network would hold it."""
    return ec.generate_private_key(ec.SECP256R1())
