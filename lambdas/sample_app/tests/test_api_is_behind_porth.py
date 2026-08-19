"""The sample app's API must be authorized by Porth, and same-origin (PORTH-612).

Two halves, and EITHER ALONE STILL FAILS:

* no authorizer -> requests arrive with no requestContext.authorizer.lambda,
  tenant_id is None, and middleware.py 401s before any permission is consulted;
* wrong origin  -> the session cookie is scoped to the zone, so a call to the raw
  execute-api host never carries it and the authorizer resolves no session.

The failure this guards against is not loud. The app returns 401, the SPA reads
that as a dead session and re-runs the Porth login, which SUCCEEDS, so it retries
and loops — and Porth's own logs stay clean throughout, because these routes never
reach Porth. It cost an evening to find once.
"""
from __future__ import annotations

import pathlib

import pytest

yaml = pytest.importorskip("yaml")

TEMPLATE = pathlib.Path(__file__).resolve().parents[3] / "template.yml"


def _template() -> dict:
    class _Loader(yaml.SafeLoader):
        pass

    def _passthrough(loader, tag_suffix, node):
        if isinstance(node, yaml.ScalarNode):
            return {tag_suffix: loader.construct_scalar(node)}
        if isinstance(node, yaml.SequenceNode):
            return {tag_suffix: loader.construct_sequence(node)}
        return {tag_suffix: loader.construct_mapping(node)}

    _Loader.add_multi_constructor("!", _passthrough)
    return yaml.load(TEMPLATE.read_text(), Loader=_Loader)


@pytest.fixture(scope="module")
def resources() -> dict:
    return _template()["Resources"]


# --------------------------------------------------------------------------
# half one: the authorizer
# --------------------------------------------------------------------------


def test_the_api_declares_a_porth_authorizer(resources):
    auth = resources["SampleAppApi"]["Properties"]["Auth"]

    assert auth.get("DefaultAuthorizer"), "the API has no default authorizer"
    authorizer = auth["Authorizers"][auth["DefaultAuthorizer"]]
    assert authorizer["FunctionArn"], "the authorizer names no function"


def test_the_context_lands_where_the_app_reads_it(resources):
    """EnableSimpleResponses must be false.

    auth_context.py reads requestContext.authorizer.lambda. Simple responses put
    the context somewhere else, so the app would see nothing and 401 — the same
    symptom as having no authorizer at all.
    """
    auth = resources["SampleAppApi"]["Properties"]["Auth"]
    authorizer = auth["Authorizers"][auth["DefaultAuthorizer"]]

    assert authorizer["AuthorizerPayloadFormatVersion"] == "2.0"
    assert authorizer["EnableSimpleResponses"] is False


def test_there_is_no_identity_source(resources):
    """PORTH-479 Path B, and the reason it matters here.

    HTTP API identity sources are AND-matched, so [Authorization, Cookie] cannot
    express "either". Requiring Authorization makes API Gateway 401 a cookie-only
    request WITHOUT INVOKING the authorizer — which is precisely the failure this
    resource was added to fix, reintroduced one line lower.
    """
    auth = resources["SampleAppApi"]["Properties"]["Auth"]
    authorizer = auth["Authorizers"][auth["DefaultAuthorizer"]]

    assert "Identity" not in authorizer, (
        "an identity source was added; cookie-authenticated calls will now be "
        "rejected before the authorizer ever runs"
    )


def test_the_function_is_attached_to_that_api(resources):
    """A declared-but-unreferenced API leaves the function on SAM's implicit one."""
    event = resources["SampleAppFunction"]["Properties"]["Events"]["ApiProxy"]

    assert "ApiId" in event["Properties"], (
        "the function still uses SAM's implicit HttpApi, which has no authorizer"
    )


# --------------------------------------------------------------------------
# half two: the origin
# --------------------------------------------------------------------------


def _behaviours(resources) -> dict:
    cf = resources["CloudFrontDistribution"]["Properties"]["DistributionConfig"]
    return {b["PathPattern"]: b for b in cf["CacheBehaviors"]}


def test_sample_calls_are_same_origin(resources):
    """Without this the zone-scoped session cookie is never sent."""
    assert "/sample/*" in _behaviours(resources), (
        "no CloudFront behaviour for /sample/* — the SPA would have to call the "
        "API cross-origin, where the session cookie does not go"
    )


def test_the_sample_behaviour_points_at_the_sample_api(resources):
    cf = resources["CloudFrontDistribution"]["Properties"]["DistributionConfig"]
    behaviour = _behaviours(resources)["/sample/*"]
    origins = {o["Id"] for o in cf["Origins"]}

    assert behaviour["TargetOriginId"] in origins, "behaviour targets a missing origin"


def test_sample_responses_are_never_cached(resources):
    """These are tenant-scoped. A cache hit serves one tenant's data to another."""
    caching_disabled = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"

    assert _behaviours(resources)["/sample/*"]["CachePolicyId"] == caching_disabled


def test_every_method_the_app_serves_is_allowed(resources):
    """The event is Method: ANY; a GET/HEAD-only behaviour would break writes."""
    allowed = set(_behaviours(resources)["/sample/*"]["AllowedMethods"])

    assert {"POST", "PUT", "PATCH", "DELETE"} <= allowed
