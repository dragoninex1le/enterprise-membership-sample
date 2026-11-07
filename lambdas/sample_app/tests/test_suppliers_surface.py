"""The supplier portal's place in the template.

Each check is a way the portal could deploy and quietly not work:

* the session route behind an authorizer -> a supplier, who has no Porth token yet,
  can never get one;
* /suppliers/* without the bearer authorizer -> Porth never resolves the session and
  the app sees no Director;
* the portal's role not named -> Porth's Terraform cannot list it, and every session
  is refused at Porth's key policy;
* anyone else able to write buyer links -> a tenant context read back from them could
  have been put there by something other than the linking admin;
* the portal able to read SupplierLink's PRIVATE key -> EMS could forge assertions;
* no /suppliers session binding -> the routes run under Porth's role, not the app's.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from sample_app.tests.test_bearer_surface import _template

ROOT = pathlib.Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def res() -> dict:
    return _template()["Resources"]


def _route(res, key):
    for r in res.values():
        p = r.get("Properties", {})
        if r["Type"] == "AWS::ApiGatewayV2::Route" and p["ApiId"] == {"Ref": "SampleAppSuppliersApi"} and p["RouteKey"] == key:
            return p
    raise KeyError(key)


def _target(res, route) -> dict:
    name = route["Target"]["Sub"].removeprefix("integrations/${").removesuffix("}")
    return res[name]["Properties"]["IntegrationUri"]


def test_the_session_route_is_open_and_served_by_the_portal(res):
    route = _route(res, "POST /session")
    assert route["AuthorizationType"] == "NONE"
    assert _target(res, route) == {"GetAtt": "SupplierPortalFunction.Arn"}


def test_supplier_routes_are_the_apps_behind_porths_bearer_authorizer(res):
    route = _route(res, "ANY /{proxy+}")
    assert (route["AuthorizationType"], route["AuthorizerId"]) == ("CUSTOM", {"Ref": "SampleAppSuppliersAuthorizer"})
    assert _target(res, route) == {"GetAtt": "SampleAppFunction.Arn"}
    auth = res["SampleAppSuppliersAuthorizer"]["Properties"]
    assert "PorthBearerAuthorizerFunctionArn" in auth["AuthorizerUri"]["Sub"]
    assert (auth["IdentitySource"], auth["AuthorizerResultTtlInSeconds"]) == (["$request.header.Authorization"], 0)


def test_suppliers_is_mapped_on_both_api_domains(res):
    mapped = {(r["Properties"]["DomainName"]["Ref"], r["Properties"]["ApiMappingKey"])
              for r in res.values() if r["Type"] == "AWS::ApiGatewayV2::ApiMapping"
              and r["Properties"]["ApiId"] == {"Ref": "SampleAppSuppliersApi"}}
    assert mapped == {("TenantApiDomain", "suppliers"), ("PlatformApiDomain", "suppliers")}


def test_the_portal_role_is_named_and_holds_its_half_of_the_mint_grant(res):
    role = res["SupplierPortalRole"]["Properties"]
    assert role["RoleName"] == {"Sub": "ems-supplier-portal-${EnvironmentSlot}"}
    by_sid = {s["Sid"]: s for s in role["Policies"][0]["PolicyDocument"]["Statement"]}
    assert by_sid["SignMintRequests"]["Condition"]["ForAnyValue:StringEquals"]["kms:ResourceAliases"] == {
        "Sub": "alias/porth-delegated-mint-request-${PorthBranch}"}
    assert by_sid["CallPorthMint"]["Resource"]["Sub"].endswith("function:porth-${PorthBranch}-delegated-mint")
    assert by_sid["PorthServiceDocuments"]["Resource"]["Sub"].endswith("/services/*")


def _statements(res):
    for name, r in res.items():
        for policy in r.get("Properties", {}).get("Policies", []) or []:
            for stmt in policy.get("PolicyDocument", {}).get("Statement", []):
                actions = stmt.get("Action", [])
                yield name, ([actions] if isinstance(actions, str) else actions), json.dumps(stmt.get("Resource", ""))


def test_only_the_portal_writes_buyer_links(res):
    writers = {name for name, actions, resource in _statements(res)
               if "SupplierLinksTable" in resource and "dynamodb:PutItem" in actions}
    assert writers == {"SupplierPortalRole"}


def test_the_portal_can_read_the_public_key_but_not_the_private_one(res):
    portal = [resource for name, actions, resource in _statements(res) if name == "SupplierPortalRole"]
    assert any("supplierlink/public-key" in r for r in portal)
    assert not any("private-key" in r or "supplierlink/*" in r for r in portal)


def test_suppliers_is_bound_to_the_apps_role():
    bindings = json.loads((ROOT / "deploy" / "porth" / "session-policy" / "index.template.json").read_text())["bindings"]
    assert bindings["api-{{ENV_SLOT}}:/suppliers"] == bindings["api-{{ENV_SLOT}}:/sample"]
