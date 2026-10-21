"""The one seam to AWS. Tests replace `client`; nothing else in the adapter imports boto3."""
from __future__ import annotations

import boto3


def client(service: str, **kwargs):
    return boto3.client(service, **kwargs)
