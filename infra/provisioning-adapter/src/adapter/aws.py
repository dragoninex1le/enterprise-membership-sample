"""The one seam to AWS. Tests replace `client` and `resource`; nothing else in the adapter imports
boto3 - porth-common is handed what these return, never left to build its own."""
from __future__ import annotations

import boto3


def client(service: str, **kwargs):
    return boto3.client(service, **kwargs)


def resource(service: str, **kwargs):
    return boto3.resource(service, **kwargs)
