"""The app reads its Porth context through the shared Director (PORTH-613).

These replace test_middleware.py, which tested a parser this app should never
have had. The parse is the library's; what is worth asserting here is the
*binding* — that this app attaches its own subclass, that handlers get the
tenant from the authorizer rather than from a parameter, and that the two
refusals stay distinguishable.
"""
from __future__ import annotations

import pytest

from porth_common.protocols.cloud_clients import DOCUMENT_STORE
from sample_app.director import SampleAppDirector
from sample_app.dependencies import require_permission


def _event(ctx: dict) -> dict:
    return {"requestContext": {"authorizer": {"lambda": ctx}}}


def _director(**ctx) -> SampleAppDirector:
    """A Director as the authorizer produces one.

    PORTH-594 — `environment` defaults in here because the authorizer always
    sends it and the key is built from it. That this helper had no environment
    at all, and that the repository raised the moment one was required, is the
    same gap in miniature: a fixture that cannot represent an axis cannot notice
    the axis is missing. Override it to assert on the refusal.
    """
    ctx.setdefault("environment", "e-test")
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


def test_the_repository_uses_the_requests_own_credentials(monkeypatch):
    """The narrowed connection, not the ambient identity (PORTH-586).

    This is the inverse of what PORTH-616 asserted, because what arrives changed.
    Then, a catch-all binding handed every request Porth's ``porth-tenant-{env}``
    role, which correctly refused this app's table, and the ambient execution
    role was the only workable source. Now the session-policy index binds this
    app's host to its own role, so ``self.resource()`` yields credentials that
    are granted this table and narrowed to one tenant.

    Asserted on the SOURCE, in both directions — that the narrowed connection is
    used AND that the ambient one is not. Asserting only that ``resource`` was
    called is how the wrong credential source passed review twice before, and
    the version of this test that checked a call rather than an outcome is the
    reason PORTH-616 existed at all.
    """
    import sample_app.director as director_module

    director = _director(tenant_id="ems-test", permissions="")
    narrowed_capabilities = []
    ambient_calls = []

    class _Resource:
        def Table(self, name):
            return object()

    monkeypatch.setattr(
        SampleAppDirector,
        "resource",
        lambda self, capability: narrowed_capabilities.append(capability) or _Resource(),
    )
    monkeypatch.setattr(
        director_module,
        "boto3",
        type("_NoBoto", (), {"resource": staticmethod(
            lambda *a, **k: ambient_calls.append(a) or _Resource())})(),
        raising=False,
    )

    repository = director.repository

    assert narrowed_capabilities == [DOCUMENT_STORE], (
        "the repository was not built from the request's narrowed connection; "
        f"resource() saw {narrowed_capabilities}"
    )
    assert not ambient_calls, (
        "the repository reached its table on the ambient execution role. That "
        "grant is gone from SampleAppFunction, so this would fail at runtime "
        "with AccessDenied rather than quietly reading every tenant's rows"
    )
    assert repository is director.repository, "a new connection per access"


def test_the_request_serving_function_holds_no_standing_table_grant():
    """Narrowing is only a boundary while there is nothing underneath it.

    A DynamoDBCrudPolicy on SampleAppFunction is unconditioned CRUD on the whole
    table for every tenant. With one present, any path that lost its narrowed
    credentials would keep working against everyone's rows and nothing would
    say so — which is what PORTH-550 removed from Porth's own API function.
    """
    import pathlib
    import re

    template = (pathlib.Path(__file__).resolve().parents[3] / "template.yml").read_text()
    # Ends at the next TOP-LEVEL thing — any line indented exactly two spaces —
    # rather than at a named resource. Naming one made the boundary a fact about
    # what happened to come next in the file: PORTH-621 inserted a role between
    # the two, and this test read that role's grants as SampleAppFunction's. It
    # failed, which is the good outcome, but it failed for a reason that had
    # nothing to do with its subject.
    block = re.search(r"\n  SampleAppFunction:\n(.*?)(?=\n  \S)", template, re.S)
    assert block, "SampleAppFunction not found in template.yml"

    # Comments only, stripped — the first version of this test matched the
    # comment explaining the grant's absence and failed on the very change it
    # was written to protect.
    yaml_only = "\n".join(
        line for line in block.group(1).splitlines()
        if not line.strip().startswith("#")
    )
    assert "DynamoDBCrudPolicy" not in yaml_only, (
        "SampleAppFunction holds a standing grant on its table again. The "
        "request path is served by credentials the authorizer minted; a role "
        "underneath them makes the narrowing advisory."
    )
    # PORTH-599 narrowed this from "no Policies block at all".
    #
    # That assertion made a real argument — anything granted here sits on the
    # ambient identity, underneath the request's narrowing — and it was right
    # for an app that only ever touched its own table. Becoming an originating
    # service on the internal plane requires two grants that are not data
    # access and cannot be obtained per-request: minting a context envelope, and
    # being allowed to call the callee. ADR-Z11 puts kms:Sign on exactly this
    # kind of principal ("originating registered-service roles", Q10).
    #
    # So the guard becomes an ALLOW-LIST rather than a prohibition, which is
    # stronger in the direction that matters: a third grant of any kind fails
    # here, including any form of table access, however it is spelled.
    #
    # The residual risk is real and worth naming rather than asserting away.
    # kms:Sign on this role is ambient: `mint_token` takes a tenant id as a
    # free string, so a call site that built an envelope by hand could mint for
    # a tenant other than the request's, and ffug would trust it. What prevents
    # that is TS-MC.1 — envelopes are derivable only from a Director bound to a
    # validated tenant — and ffug_client.py is the single call site, which is
    # why it goes through director.build_context_envelope() and never
    # mint_token(). If a second call site appears, this is the comment to read.
    # Matches both `Action: kms:Sign` and a list item `- kms:Sign`, and anchors
    # to end-of-line so an `arn:aws:ssm:...` Resource cannot be read as the
    # action `arn:aws`. The single-form-only version of this silently found
    # nothing the moment kms gained a second action (PORTH-604) — a guard that
    # stops seeing its subject passes rather than fails.
    granted = set(
        re.findall(r"(?m)^\s*(?:Action:\s*|-\s+)([a-z0-9]+:[A-Za-z]+)\s*$", yaml_only)
    )
    assert granted, "the grant scraper matched nothing — it has stopped seeing its subject"
    assert granted == {
        "kms:Sign",
        "kms:DescribeKey",
        "lambda:InvokeFunction",
        "ssm:GetParameter",
    }, (
        f"SampleAppFunction's standing grants changed: {sorted(granted)}. Only "
        f"minting context, invoking ffug, and reading the two documents that "
        f"resolve the internal plane are allowed here — everything else a "
        f"request needs comes from the credentials the authorizer minted for "
        f"it, and a grant underneath those makes the narrowing advisory."
    )
    # PORTH-603/623/625 — bounded to exactly what the internal plane needs: the
    # D3 registry, the D7.4 endpoint map, and the signing-key documents.
    #
    # signing-keys/* is a prefix and the others are exact, which is the shape of
    # the contract rather than laziness: as of porth-common 0.0.11 there is one
    # document PER SERVICE at signing-keys/{service_id}, and a verifier fetches
    # the document of whichever service the token claims to be from. A wildcard
    # over /porth/{branch}/* would be something else entirely — a standing read
    # over every parameter the install has, session-policy templates included.
    reads = re.findall(r"parameter/porth/\$\{PorthBranch\}/([^\s]+)", yaml_only)
    assert sorted(reads) == ["service-endpoints", "services", "signing-keys/*"], reads

    assert "kms:Verify" not in yaml_only, (
        "SampleAppFunction holds kms:Verify. It is the CALLER on the internal "
        "plane, not a receiver; holding Sign and Verify together would let it "
        "verify its own forgeries."
    )


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

    assert "ENV#e-test#TENANT#t-test" in _condition_values(condition), (
        "the query was not scoped to the Director's tenant AND environment. "
        "str() on a boto3 condition hides its operands, so this walks the "
        "expression instead — an assertion against the repr passes no matter "
        "which tenant was used."
    )


def test_a_director_without_an_environment_cannot_build_a_repository():
    """PORTH-594's fail-closed half, asserted rather than assumed.

    An empty environment composes ENV##TENANT#{tenant}: a key that writes
    successfully, matches no session policy, and is never read back. The symptom
    would be "the invoice I just created is not in the list", several layers from
    the cause — so the repository refuses to exist instead.
    """
    from sample_app.repository import ScopeMissingError

    director = _director(tenant_id="t-1", environment="")
    with pytest.raises(ScopeMissingError):
        _ = director.repository


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


# --------------------------------------------------------------------------
# what an ORIGINATING service needs, enumerated in one place
# --------------------------------------------------------------------------


def test_the_caller_carries_everything_the_internal_plane_reads():
    """The checklist the allow-list above structurally cannot be.

    Four separate deploys were spent discovering these one at a time, each
    surfacing only after the previous was fixed, because every one of them is
    read at a different depth of the same call and the first to fail hides the
    rest:

        ssm:GetParameter  /porth/{b}/services        D3 registry     (PORTH-603)
        ssm:GetParameter  /porth/{b}/service-endpoints  D7.4 map     (PORTH-603)
        PORTH_CONTEXT_SIGNING_KEY_ALIAS               mint_token     (PORTH-604)
        kms:DescribeKey                               _resolve_kid   (PORTH-604)

    An allow-list guards the ceiling and says nothing about absence. This is
    the other half, and it is deliberately a flat list rather than anything
    clever: the value is that a new requirement gets written down HERE, once,
    instead of being found in production a fifth time.

    Why the callee's configuration was no guide: ffug carries the registry read
    but needs no signing key at all, because a verifier follows the `kid` in the
    token header. Caller and receiver are not mirror images, and treating them
    as such is what made each of these invisible.
    """
    import pathlib
    import re

    template = (pathlib.Path(__file__).resolve().parents[3] / "template.yml").read_text()
    block = re.search(
        r"\n  SampleAppFunction:\n(.*?)\n  SampleAppEventConsumerFunction:", template, re.S
    )
    assert block, "SampleAppFunction not found in template.yml"
    # Comments stripped for the same reason as the test above: the comments here
    # NAME these variables while explaining them, so an unstripped match would
    # pass on the strength of the prose describing what is missing.
    yaml_only = "\n".join(
        line for line in block.group(1).splitlines() if not line.strip().startswith("#")
    )
    variables = set(re.findall(r"^\s{10}([A-Z_][A-Z_0-9]*):", yaml_only, re.M))

    required = {
        # this app's identity on the plane, and the audience ffug checks
        "PORTH_SERVICE_ID",
        # the CONFIGURATION axis — which /porth/{branch}/… documents to read
        "PORTH_BRANCH",
        # the ADR-Z8 DATA axis — which slot the envelope is minted for
        "PORTH_FIXED_ENVIRONMENT",
        # the key mint_token describes, then signs with
        "PORTH_CONTEXT_SIGNING_KEY_ALIAS",
    }
    missing = required - variables
    assert not missing, (
        f"SampleAppFunction is missing {sorted(missing)}. Each is read at a "
        f"different depth of one ServiceClient call, so the first to fail hides "
        f"the rest — which is why these cost four deploys to find individually."
    )


# --- the app can be heard (PORTH-622) ----------------------------------------


def test_the_app_sets_a_log_level_so_its_own_lines_survive():
    """A log line that never emits is a hop nobody can witness.

    Nothing configured a level, so every module logger inherited Lambda's root
    default of WARNING and every `log.info` in this app was discarded. It hid
    perfectly: the app worked and the log group was empty, and an empty log
    group reads as "quiet" rather than "muted".

    It surfaced when PORTH-622 came to assert one trace_id across all four hops
    of the async round trip and could only show three — not because the
    initiating hop had not happened, but because it had never been able to say
    so. `sample_app.fingerprint` had been silent on the SYNCHRONOUS path since
    PORTH-599 for the same reason.
    """
    import logging

    import sample_app.handler  # noqa: F401 — importing is what configures it

    level = logging.getLogger("sample_app").level

    assert level and level <= logging.INFO, (
        f"the sample_app logger is at {logging.getLevelName(level)}; its own "
        f"INFO lines will be discarded and every hop it makes will be "
        f"unwitnessable"
    )


def test_the_level_is_set_on_the_package_not_the_root():
    """Turning up this app must not turn up every library it imports.

    basicConfig() on the root would make botocore's DEBUG chatter arrive with
    it, which is how a log group becomes unreadable and then ignored.
    """
    import logging

    import sample_app.handler  # noqa: F401

    assert logging.getLogger().level != logging.DEBUG, (
        "the root logger was configured — this app's verbosity should not be "
        "the whole runtime's"
    )
