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

    the Director reads requestContext.authorizer.lambda. Simple responses put
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
    """The behaviours of a SHARED-HOST slot — the one where these halves apply.

    PORTH-656: CacheBehaviors is `!If [IsTenantApiHosts, NoValue, [...]]`. On a
    tenant-API-host slot CloudFront serves the UI only and the API is its own
    host, so there is nothing to be same-origin with; see
    test_tenant_api_hosts.py for that shape.
    """
    cf = resources["CloudFrontDistribution"]["Properties"]["DistributionConfig"]
    behaviours = cf["CacheBehaviors"]
    if isinstance(behaviours, dict) and "If" in behaviours:
        behaviours = behaviours["If"][2]
    return {b["PathPattern"]: b for b in behaviours}


def test_sample_calls_are_same_origin(resources):
    """Without this the zone-scoped session cookie is never sent."""
    assert "/sample/*" in _behaviours(resources), (
        "no CloudFront behaviour for /sample/* — the SPA would have to call the "
        "API cross-origin, where the session cookie does not go"
    )


def test_the_sample_behaviour_points_at_the_sample_api(resources):
    cf = resources["CloudFrontDistribution"]["Properties"]["DistributionConfig"]
    behaviour = _behaviours(resources)["/sample/*"]
    origins = cf["Origins"]
    if isinstance(origins, dict) and "If" in origins:
        # PORTH-656: `!If [IsTenantApiHosts, [S3 only], [S3 + API origins]]` —
        # the behaviours live on the shared-host branch, and so must their origins.
        origins = origins["If"][2]
    ids = {o["Id"] for o in origins}

    assert behaviour["TargetOriginId"] in ids, "behaviour targets a missing origin"


def test_a_tenant_api_host_slot_has_the_ui_origin_only(resources):
    """PORTH-656: no API behaviours there, so no API origins either."""
    cf = resources["CloudFrontDistribution"]["Properties"]["DistributionConfig"]
    assert [o["Id"] for o in cf["Origins"]["If"][1]] == ["S3Origin"]


def test_the_sample_api_domain_exists_only_on_shared_host_slots(resources):
    for name in ("SampleAppApiDomain", "SampleAppApiMapping"):
        assert resources[name].get("Condition") == "IsSharedHost", name


def test_sample_responses_are_never_cached(resources):
    """These are tenant-scoped. A cache hit serves one tenant's data to another."""
    caching_disabled = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"

    assert _behaviours(resources)["/sample/*"]["CachePolicyId"] == caching_disabled


def test_every_method_the_app_serves_is_allowed(resources):
    """The event is Method: ANY; a GET/HEAD-only behaviour would break writes."""
    allowed = set(_behaviours(resources)["/sample/*"]["AllowedMethods"])

    assert {"POST", "PUT", "PATCH", "DELETE"} <= allowed


# --------------------------------------------------------------------------
# preflights: every authorized browser route has an open OPTIONS route that wins
# --------------------------------------------------------------------------


def _browser_routes(resources):
    """(path, method, open?) for every HttpApi event on the browser API, any function."""
    for res in resources.values():
        for event in (res.get("Properties", {}).get("Events") or {}).values():
            props = event.get("Properties", {})
            if event.get("Type") != "HttpApi" or props.get("ApiId") != {"Ref": "SampleAppApi"}:
                continue
            open_ = (props.get("Auth") or {}).get("Authorizer") == "NONE"
            yield props["Path"], props["Method"].upper(), open_


def test_every_authorized_browser_path_has_an_open_preflight(resources):
    """A preflight carries no cookie. API Gateway picks the most specific PATH first and
    only then the method, so an open `OPTIONS /a/{proxy+}` does not cover an authorized
    `ANY /a/b`: the preflight lands on `ANY /a/b`, the authorizer denies it (403), and
    the browser reports a network error. Each authorized path needs OPTIONS on itself."""
    routes = list(_browser_routes(resources))
    open_options = {path for path, method, open_ in routes if method == "OPTIONS" and open_}
    authorized = {path for path, method, open_ in routes if not open_ and method != "OPTIONS"}

    missing = sorted(authorized - open_options)
    assert not missing, f"authorized browser paths with no open OPTIONS route of their own: {missing}"


# --------------------------------------------------------------------------
# Porth's execute-api policy index covers every prefix the app serves
# --------------------------------------------------------------------------

AUTH_POLICY_INDEX = TEMPLATE.parent / "deploy" / "porth" / "auth-policy" / "index.json"


def test_porths_policy_index_covers_every_prefix_the_app_serves(resources):
    """From Porth 0.4.1 (PORTH-642) an authorized path that no entry in
    /porth/<env>/auth-policy/index covers is DENIED: `deny_reason: no_policy`, a 403
    with no CORS headers, which the SPA reports only as "Network Error". The index is
    seeded from deploy/porth/auth-policy/index.json, so it must name every top-level
    prefix the authorizers see: the browser API's routes, and the bearer APIs'
    mapping keys (their paths arrive prefixed with the key)."""
    import json

    index = json.loads(AUTH_POLICY_INDEX.read_text())
    served = {"/" + path.strip("/").split("/")[0] for path, method, open_ in _browser_routes(resources)
              if not open_}
    for res in resources.values():
        if res.get("Type") == "AWS::ApiGatewayV2::Stage":
            key = (res["Properties"].get("StageVariables") or {}).get("mapping_key")
            if key:
                served.add(f"/{key}")

    missing = sorted(p for p in served if p not in index)
    assert not missing, f"prefixes the app serves that Porth's policy index does not cover: {missing}"
