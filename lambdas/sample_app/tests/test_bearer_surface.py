"""The bearer surface: /mcp and connector tokens reach the app on Porth's bearer authorizer.

Porth INSTALL §4a ("Surfaces", "The MCP door and the bearer surface"). The app's
API serves the SPA's cookie sessions on the BROWSER authorizer, which denies a
request with no session cookie whatever else it carries. An MCP client and a
connector's prth_ token send a bearer, so they need the app's own bearer API.

Each assertion below is one of §4a's requirements; a miss is quiet in production:

* no identity source            -> a tokenless call reaches the authorizer and is
                                   denied 403, so an MCP client never starts OAuth
                                   discovery (it starts on 401);
* a result TTL                  -> one token's answer is served to the next caller;
* only the browser role trusted -> the bearer authorizer cannot assume the app's
                                   role, every MCP call is denied at the assume;
* no /mcp binding               -> /mcp matches the `/` binding and gets PORTH's
                                   role, which cannot read the app's table;
* no `.well-known` mapping      -> the client cannot find the authorization server.
"""
from __future__ import annotations

import json
import pathlib

import pytest

yaml = pytest.importorskip("yaml")

ROOT = pathlib.Path(__file__).resolve().parents[3]
TEMPLATE = ROOT / "template.yml"
SESSION_INDEX = ROOT / "deploy" / "porth" / "session-policy" / "index.template.json"


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
def template() -> dict:
    return _template()


@pytest.fixture(scope="module")
def resources(template) -> dict:
    return template["Resources"]


def test_the_bearer_api_uses_porths_bearer_authorizer(resources):
    props = resources["SampleAppBearerAuthorizer"]["Properties"]
    assert props["AuthorizerType"] == "REQUEST"
    assert props["AuthorizerPayloadFormatVersion"] == "2.0"
    assert props["EnableSimpleResponses"] is False
    assert "PorthBearerAuthorizerFunctionArn" in props["AuthorizerUri"]["Sub"]
    assert "PorthAuthorizerFunctionArn" not in props["AuthorizerUri"]["Sub"], (
        "that is the BROWSER authorizer on a tenant-API-host slot"
    )


def test_a_tokenless_call_is_a_401_and_no_answer_is_cached(resources):
    props = resources["SampleAppBearerAuthorizer"]["Properties"]
    assert props["IdentitySource"] == ["$request.header.Authorization"]
    assert props["AuthorizerResultTtlInSeconds"] == 0


def test_every_bearer_route_is_authorized(resources):
    routes = [r for r in resources.values() if r["Type"] == "AWS::ApiGatewayV2::Route"
              and r["Properties"]["ApiId"] == {"Ref": "SampleAppBearerApi"}]
    # $default: a request for exactly .../mcp has an empty path (test_mapping_key.py).
    assert {r["Properties"]["RouteKey"] for r in routes} == {"ANY /", "ANY /{proxy+}", "$default"}
    for r in routes:
        assert r["Properties"]["AuthorizationType"] == "CUSTOM"
        assert r["Properties"]["AuthorizerId"] == {"Ref": "SampleAppBearerAuthorizer"}


def test_mcp_and_well_known_are_mapped_on_both_api_domains(resources):
    mappings = {
        (r["Properties"]["DomainName"]["Ref"], r["Properties"].get("ApiMappingKey", "")):
            r["Properties"]["ApiId"]
        for r in resources.values() if r["Type"] == "AWS::ApiGatewayV2::ApiMapping"
        and isinstance(r["Properties"]["DomainName"], dict)
    }
    for domain in ("TenantApiDomain", "PlatformApiDomain"):
        assert mappings[(domain, "mcp")] == {"Ref": "SampleAppBearerApi"}
        assert mappings[(domain, ".well-known")] == {"Ref": "PorthBearerHttpApiId"}
        # The SPA's routes stay on the browser API at the root.
        assert mappings[(domain, "")] == {"Ref": "SampleAppApi"}


def test_the_apps_role_trusts_both_authorizers(resources):
    statement = resources["SampleAppTenantRole"]["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]
    when_bearer, otherwise = statement["Principal"]["AWS"]["If"][1:]
    assert {"Ref": "PorthBearerAuthorizerFunctionRoleArn"} in when_bearer
    assert {"Ref": "PorthAuthorizerFunctionRoleArn"} in when_bearer
    assert set(statement["Action"]) == {"sts:AssumeRole", "sts:TagSession"}


def test_api_gateway_may_invoke_the_bearer_authorizer(resources):
    stmt = resources["SampleAppAuthorizerInvokeRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"][0]
    when_bearer = stmt["Resource"]["If"][1]
    assert {"Ref": "PorthBearerAuthorizerFunctionArn"} in when_bearer


def test_mcp_is_bound_to_the_apps_role_not_porths():
    bindings = json.loads(SESSION_INDEX.read_text())["bindings"]
    assert bindings["api-{{ENV_SLOT}}:/mcp"] == bindings["api-{{ENV_SLOT}}:/sample"]
    assert "ems-sample-app" in bindings["api-{{ENV_SLOT}}:/mcp"]["role_arn"]
