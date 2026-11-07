import os
import pathlib
import sys

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

os.environ.setdefault("CLOUDFRONT_ALIAS", "*.porth-dau.ems.estynsoftware.cloud")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")


@pytest.fixture(scope="session")
def network_key():
    """SupplierLink's key pair, as the network would hold it."""
    return ec.generate_private_key(ec.SECP256R1())
