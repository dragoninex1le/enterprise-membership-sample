"""PORTH-656 — on a tenant API host, CORS answers only that host's own UI."""
from __future__ import annotations

import asyncio

import pytest

from sample_app.cors import HostBoundOriginMiddleware, own_ui_origin

ALIAS = "*.porth-dau.ems.estynsoftware.cloud"
BASE = "porth-dau.ems.estynsoftware.cloud"


@pytest.mark.parametrize(
    "host,expected",
    [
        (f"acme.api.{BASE}", f"https://acme.{BASE}"),
        (f"ACME.api.{BASE}:443", f"https://acme.{BASE}"),
        (f"api.{BASE}", f"https://{BASE}"),
        (f"sample-api.{BASE}", None),          # the shared-host custom domain
        (f"acme.{BASE}", None),                # a UI host
        (f"a.b.api.{BASE}", None),             # not one label
        (f"acme.api.porth-sample.ems.estynsoftware.cloud", None),  # another slot
    ],
)
def test_own_ui_origin(host, expected):
    assert own_ui_origin(host, ALIAS) == expected


def test_no_alias_means_no_api_hosts():
    assert own_ui_origin(f"acme.api.{BASE}", "") is None


def _seen_origin(host, origin):
    seen = {}

    async def app(scope, receive, send):
        seen["origin"] = dict(scope["headers"]).get(b"origin")

    headers = [(b"host", host.encode())] + ([(b"origin", origin.encode())] if origin else [])
    asyncio.run(HostBoundOriginMiddleware(app, ALIAS)({"type": "http", "headers": headers}, None, None))
    return seen["origin"]


def test_the_hosts_own_ui_passes():
    assert _seen_origin(f"acme.api.{BASE}", f"https://acme.{BASE}") == f"https://acme.{BASE}".encode()


@pytest.mark.parametrize(
    "origin", [f"https://other.{BASE}", f"https://{BASE}", "https://evil.example"]
)
def test_any_other_origin_is_dropped_on_an_api_host(origin):
    assert _seen_origin(f"acme.api.{BASE}", origin) is None


def test_other_hosts_are_untouched():
    assert _seen_origin(f"sample-api.{BASE}", f"https://other.{BASE}") == f"https://other.{BASE}".encode()


def test_preflight_end_to_end_through_the_app(monkeypatch):
    """The real app, real middleware order: own UI gets credentials, another
    tenant's UI gets no CORS headers at all."""
    monkeypatch.setenv("CLOUDFRONT_ALIAS", ALIAS)
    import importlib

    import sample_app.handler as handler
    importlib.reload(handler)
    from starlette.testclient import TestClient

    client = TestClient(handler.app, base_url=f"https://acme.api.{BASE}")
    pre = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "x-csrf-token"}

    ok = client.options("/sample/ar", headers={"Origin": f"https://acme.{BASE}", **pre})
    assert ok.headers.get("access-control-allow-origin") == f"https://acme.{BASE}"
    assert ok.headers.get("access-control-allow-credentials") == "true"
    assert "x-csrf-token" in ok.headers.get("access-control-allow-headers", "").lower()

    other = client.options("/sample/ar", headers={"Origin": f"https://other.{BASE}", **pre})
    assert "access-control-allow-origin" not in other.headers
