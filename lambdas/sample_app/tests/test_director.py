"""The app reads its Porth context through the shared Director (PORTH-613).

These replace test_middleware.py, which tested a parser this app should never
have had. The parse is the library's; what is worth asserting here is the
*binding* — that this app attaches its own subclass, that handlers get the
tenant from the authorizer rather than from a parameter, and that the two
refusals stay distinguishable.
"""
from __future__ import annotations

import pytest

from sample_app.director import SampleAppDirector
from sample_app.dependencies import require_permission


def _event(ctx: dict) -> dict:
    return {"requestContext": {"authorizer": {"lambda": ctx}}}


def _director(**ctx) -> SampleAppDirector:
    return SampleAppDirector(_event(ctx))


class _State:
    def __init__(self, director=None):
        self.director = director


class _Request:
    def __init__(self, director=None):
        self.state = _State(director)


# --------------------------------------------------------------------------
# the binding
# --------------------------------------------------------------------------


def test_it_is_a_porth_director():
    """Inherited, not reimplemented — the whole point of PORTH-613."""
    from porth_common.director import Director

    assert issubclass(SampleAppDirector, Director)


def test_the_app_attaches_its_own_subclass():
    from sample_app.director import DirectorMiddleware

    middleware = DirectorMiddleware(app=None)

    assert middleware._director_cls is SampleAppDirector


def test_identity_comes_from_the_authorizer_context():
    director = _director(
        tenant_id="ems-test",
        user_id="u-1",
        roles="tenant-admin",
        permissions="ar.invoices.read,dashboard.read",
    )

    assert director.tenant_id == "ems-test"
    assert director.user_id == "u-1"
    assert director.roles == ["tenant-admin"]
    assert director.permissions == {"ar.invoices.read", "dashboard.read"}


# --------------------------------------------------------------------------
# the two refusals, which must not look alike
# --------------------------------------------------------------------------


def test_a_held_permission_is_allowed():
    guard = require_permission("ar.invoices.read")
    request = _Request(_director(tenant_id="t", permissions="ar.invoices.read"))

    assert guard(request) is None


def test_a_missing_permission_is_403():
    """The caller is authenticated; they simply may not do this."""
    from fastapi import HTTPException

    guard = require_permission("ar.invoices.write")
    request = _Request(_director(tenant_id="t", permissions="ar.invoices.read"))

    with pytest.raises(HTTPException) as exc:
        guard(request)
    assert exc.value.status_code == 403
    assert "ar.invoices.write" in exc.value.detail


def test_no_director_at_all_is_401_not_403():
    """The distinction that cost an evening (PORTH-612).

    No Director means the request never carried an authorizer context — the API
    was not behind the authorizer, or the call never reached it. Reporting that
    as 403 sends the reader hunting for a missing grant; there is no grant that
    would have helped.
    """
    from fastapi import HTTPException

    guard = require_permission("ar.invoices.read")

    with pytest.raises(HTTPException) as exc:
        guard(_Request(director=None))
    assert exc.value.status_code == 401
    assert "not behind the Porth authorizer" in exc.value.detail


# --------------------------------------------------------------------------
# data access
# --------------------------------------------------------------------------


def test_the_repository_uses_the_directors_own_connection(monkeypatch):
    """Not a resource built by hand from raw STS keys.

    The connection is cached and scoped to this request's credentials, so a
    handler cannot reach another tenant's partition even by asking.
    """
    director = _director(tenant_id="ems-test", permissions="")
    asked: list = []

    class _Table:
        pass

    class _Resource:
        def Table(self, name):
            asked.append(name)
            return _Table()

    monkeypatch.setattr(
        SampleAppDirector, "resource", lambda self, capability: _Resource()
    )

    repository = director.repository

    assert asked, "the repository never asked the Director for a connection"
    assert repository is director.repository, "a new connection per access"


# --------------------------------------------------------------------------
# the chain, end to end
# --------------------------------------------------------------------------
#
# Everything above tests a piece. These call a real route through a real app, so
# the whole path executes: middleware attaches the Director, get_director hands
# it to the `porth` dependency, and the handler reaches its data through it.
#
# Added because the pieces all passed while nothing ran them together — the
# conftest had a `client` fixture that no test used, so a break anywhere in the
# wiring would have gone unnoticed by a green suite.



def _condition_values(condition) -> set:
    """Every literal operand in a boto3 key condition, however nested."""
    values: set = set()
    expression = getattr(condition, "get_expression", None)
    if expression is None:
        return {condition} if isinstance(condition, str) else values
    for operand in expression()["values"]:
        if isinstance(operand, str):
            values.add(operand)
        else:
            values |= _condition_values(operand)
    return values

def test_a_route_reaches_its_data_through_the_director(client, mock_dynamodb):
    mock_dynamodb.Table.return_value.query.return_value = {
        "Items": [{"invoice_id": "i-1"}]
    }

    response = client.get("/sample/ar/invoices")

    assert response.status_code == 200
    assert response.json() == [{"invoice_id": "i-1"}]


def test_the_handler_scopes_by_the_directors_tenant(client, mock_dynamodb):
    """The tenant comes from the authorizer context, never from the caller."""
    mock_dynamodb.Table.return_value.query.return_value = {"Items": []}

    client.get("/sample/ar/invoices")

    condition = mock_dynamodb.Table.return_value.query.call_args.kwargs[
        "KeyConditionExpression"
    ]

    assert "TENANT#t-test" in _condition_values(condition), (
        "the query was not scoped to the Director's tenant. str() on a boto3 "
        "condition hides its operands, so this walks the expression instead — "
        "an assertion against the repr passes no matter which tenant was used."
    )


def test_a_route_without_the_permission_is_refused(mock_dynamodb):
    """403 from the route itself, with the Director attached and authenticated."""
    from sample_app.tests.conftest import build_director, make_test_app
    from starlette.testclient import TestClient

    director = build_director(permissions={"dashboard.read"}, dynamodb=mock_dynamodb)
    response = TestClient(make_test_app(director)).get("/sample/ar/invoices")

    assert response.status_code == 403
    assert "ar.invoices.read" in response.json()["detail"]


def test_a_write_route_needs_its_own_permission(mock_dynamodb):
    """Read does not imply write — the split the app's whole model rests on."""
    from sample_app.tests.conftest import build_director, make_test_app
    from starlette.testclient import TestClient

    director = build_director(permissions={"ar.invoices.read"}, dynamodb=mock_dynamodb)
    response = TestClient(make_test_app(director)).post(
        "/sample/ar/invoices",
        json={"customer_name": "Acme", "amount": 1.0, "due_date": ""},
    )

    assert response.status_code == 403
    assert "ar.invoices.write" in response.json()["detail"]
