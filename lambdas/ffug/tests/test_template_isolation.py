"""The isolation properties that live in IAM, asserted against template.yml.

Behaviour that lives in a permission does not show up in a code diff, and the
half of PORTH-587 that actually does the isolating is entirely in this file's
subject matter. Every assertion here is a property a reviewer would otherwise
have to hold in their head across a 700-line template — and each one, if it
silently regressed, would leave a service that still works and no longer
isolates. That failure mode has a track record: entry 3 of Porth's EMS upgrade
log is a session policy that matched no request path for three releases while
every install reported success.

These run in pytest rather than as a bespoke script in one workflow, so both
the PR gate and the deploy gate execute them.
"""

import pathlib
import re

import pytest
import yaml

TEMPLATE = pathlib.Path(__file__).resolve().parents[3] / "template.yml"


class CfnLoader(yaml.SafeLoader):
    """Enough of CloudFormation's short forms to assert on what they point at."""


def _tag(name):
    def construct(loader, node):
        if isinstance(node, yaml.ScalarNode):
            return {name: loader.construct_scalar(node)}
        if isinstance(node, yaml.SequenceNode):
            return {name: loader.construct_sequence(node, deep=True)}
        return {name: loader.construct_mapping(node, deep=True)}

    return construct


for _short in (
    "Sub", "Ref", "GetAtt", "Equals", "If", "Join", "Select", "Split",
    "FindInMap", "Not", "And", "Or", "Base64", "Condition", "ImportValue",
):
    CfnLoader.add_constructor(f"!{_short}", _tag(_short))


@pytest.fixture(scope="module")
def template():
    return yaml.load(TEMPLATE.read_text(), Loader=CfnLoader)


@pytest.fixture(scope="module")
def resources(template):
    return template["Resources"]


def statements(role):
    """Every statement, with `Fn::If` wrappers unwrapped to the branch they emit.

    Two of these grants are conditional — IAM rejects an empty Resource, so the
    KMS statements only exist when the signing key was resolved. A conditional
    grant is still a grant, and the assertions below have to see through the
    wrapper or they would pass vacuously by finding nothing.
    """
    for policy in role["Properties"].get("Policies", []):
        for statement in policy["PolicyDocument"]["Statement"]:
            if isinstance(statement, dict) and set(statement) == {"If"}:
                _condition, when_true, _when_false = statement["If"]
                yield when_true
            else:
                yield statement


def actions(role):
    found = set()
    for statement in statements(role):
        action = statement["Action"]
        found.update([action] if isinstance(action, str) else action)
    return found


# --- ffug's execution role holds no data access whatsoever -------------------


def test_the_ffug_function_has_an_explicit_role_and_no_inline_policies(resources):
    """SAM rejects Role and Policies together, so this is also how the ambient
    DynamoDB grant is kept out: there is nowhere for it to be added."""
    props = resources["FfugFunction"]["Properties"]

    assert props["Role"] == {"GetAtt": "FfugFunctionRole.Arn"}
    assert "Policies" not in props


def test_ffug_can_reach_no_table_without_narrowing_first(resources):
    """The keystone of PORTH-587, and the assertion most worth keeping.

    ffug used to carry DynamoDBCrudPolicy on its own table. With that grant
    present, a narrowing failure degrades to full-table access and every read
    still succeeds — silently, across every tenant. With it absent, the same
    failure is an AccessDenied. Fail-closed becomes a property of the
    deployment rather than a behaviour some future change could regress.
    """
    for action in actions(resources["FfugFunctionRole"]):
        assert not action.startswith("dynamodb:"), (
            f"FfugFunctionRole grants {action}; ffug must reach data only "
            f"through the credentials it narrows for itself"
        )


def test_a_conditional_grant_is_still_visible_to_these_assertions(resources):
    """Guards the helper above. If `statements()` stopped unwrapping `Fn::If`,
    every KMS assertion here would pass by finding nothing — the vacuous-pass
    failure mode that makes a green suite worse than no suite."""
    assert "kms:Verify" in actions(resources["FfugFunctionRole"])
    assert "kms:Sign" in actions(resources["PorthUatRunnerRole"])


def test_ffug_verifies_context_and_can_never_mint_it(resources):
    """Head of Security condition H1, expressed where it is enforced.

    ffug is a receiver. Its role attempting kms:Sign and being denied is what
    UAT-4 witnesses live, so granting Sign here would not merely widen a
    permission — it would delete the demonstration.
    """
    granted = actions(resources["FfugFunctionRole"])

    assert "kms:Verify" in granted
    assert "kms:Sign" not in granted


def test_ffugs_only_route_to_data_is_its_tenant_role(resources):
    assumable = [
        s["Resource"]
        for s in statements(resources["FfugFunctionRole"])
        if s["Action"] == "sts:AssumeRole"
    ]

    assert assumable == [{"GetAtt": "FfugTenantRole.Arn"}]


def test_the_narrowing_names_both_an_identity_and_a_rule(resources):
    """IAM says ffug MAY assume its tenant role. These say which role, by what rule.

    Both are read inside the credentials provider and nowhere above it, so
    nothing in ffug's own code mentions either — which is precisely why they
    need asserting here. Neither has a default: lose the identity and there is
    no role to narrow, lose the scope and there is no rule to narrow by, and
    the provider raises NarrowingUnavailableError either way rather than
    running wide. Fail-closed, but a failure at runtime is not the same thing
    as one caught on the pull request.

    The scope is a NAME, not a document. Porth's own deploy seeds the body at
    /porth/{branch}/auth-session-policy/tenant-scoped-default, and it is the
    same template the authorizer renders for a human caller — so the rule that
    isolates ffug and the rule that isolates a browser session are one rule
    with one place to change it.
    """
    env = resources["FfugFunction"]["Properties"]["Environment"]["Variables"]

    assert env["PORTH_SERVICE_DATA_IDENTITY"] == {"GetAtt": "FfugTenantRole.Arn"}
    assert env["PORTH_SERVICE_DATA_SCOPE"] == "tenant-scoped-default"


def test_ffug_can_read_the_template_its_narrowing_renders(resources):
    """The grant that makes the scope above reachable at all.

    Easy to lose, because it is a permission on a different resource than the
    one being isolated — the rule for reaching DynamoDB is fetched from the
    parameter store. Without this read the narrowing refuses before it ever
    reaches STS, and the symptom is a tenant that looks unprovisioned rather
    than a grant that is missing.
    """
    reads = [
        s for s in statements(resources["FfugFunctionRole"])
        if s["Action"] == "ssm:GetParameter"
    ]
    assert reads, "ffug cannot fetch its session-policy template"

    arns = [a["Sub"] for read in reads for a in read["Resource"]]
    assert any(arn.endswith("/auth-session-policy/*") for arn in arns), arns


# --- the tenant role's ceiling ----------------------------------------------


def test_the_tenant_role_is_bound_by_a_leading_key_condition(resources):
    """The session policy narrows to ONE tenant; this ceiling keeps the role
    from reaching anything that is not tenant-keyed at all."""
    for statement in statements(resources["FfugTenantRole"]):
        keys = statement["Condition"]["ForAllValues:StringLike"]["dynamodb:LeadingKeys"]
        assert keys == ["ENV#*#TENANT#*", "ENV#*#TENANT#*#*"]


def test_the_tenant_role_grants_no_scan(resources):
    """Scan is the one action no key condition can constrain.

    It populates no dynamodb:LeadingKeys, so ForAllValues passes vacuously
    against it — a Scan grant inside a conditioned statement reads as bounded
    and is not. Porth carries the same trap on its platform session policy
    (PORTH-580); ffug simply never scans, so it never needs one.
    """
    assert "dynamodb:Scan" not in actions(resources["FfugTenantRole"])


def test_the_tenant_role_reaches_only_ffugs_own_table(resources):
    for statement in statements(resources["FfugTenantRole"]):
        assert statement["Resource"] == {"GetAtt": "FfugTable.Arn"}


# --- the bus subscription ---------------------------------------------------


def test_the_lifecycle_rule_is_on_porths_bus_not_the_default_one(resources):
    """A rule that omits EventBusName is created against `default`, matches
    nothing, and reports no error — which is exactly how the sample app's
    EntityEvent consumer has sat inert."""
    rule = resources["FfugLifecycleFunction"]["Properties"]["Events"]["TenantLifecycle"]

    assert rule["Properties"]["EventBusName"] == {"Ref": "PorthEventBusName"}


def test_the_lifecycle_rule_matches_the_contract_channel(resources):
    """Lowercase `tenant.*` is contract v1. The capitalised `Tenant.*` domain
    events are the audit/search feed and are explicitly not this contract."""
    pattern = resources["FfugLifecycleFunction"]["Properties"]["Events"]["TenantLifecycle"][
        "Properties"
    ]["Pattern"]

    assert pattern["source"] == ["porth.user-management"]
    assert set(pattern["detail-type"]) == {
        "tenant.created",
        "tenant.updated",
        "tenant.suspended",
        "tenant.reactivated",
        "tenant.deleted",
    }


def test_the_consumer_holds_no_signing_or_narrowing_permission(resources):
    """It maintains a projection from a bus. A bus event is not an envelope,
    so there is nothing for it to verify and nothing for it to assume."""
    granted = actions(resources["FfugLifecycleFunctionRole"])

    assert not any(a.startswith(("kms:", "sts:")) for a in granted)


# --- the deletion marker is actually bounded --------------------------------


def test_the_table_expires_the_deletion_marker(resources):
    """`tenant.deleted` leaves a stripped row as the order gate against a late
    pre-deletion event, and stamps expires_at on it. Without the TTL
    specification that attribute is inert and the marker is permanent — which
    would make it residue, and residue-free teardown is a UAT-5 assertion."""
    ttl = resources["FfugTable"]["Properties"]["TimeToLiveSpecification"]

    assert ttl == {"AttributeName": "expires_at", "Enabled": True}


# --- the signer -------------------------------------------------------------


def test_the_uat_runner_can_mint_context(resources):
    """Without this grant nothing in the account can sign, the internal plane
    has no caller, and ffug's kms:Sign denial proves nothing because everything
    is denied. See Components PR #294 entries 14-15."""
    assert "kms:Sign" in actions(resources["PorthUatRunnerRole"])


# --- the guard that cost a rolled-back stack --------------------------------


LATIN1_PRINTABLE = re.compile("^[\t\n\r\x20-\x7e\xa1-\xff]*$")


def test_iam_role_descriptions_are_iam_legal(resources):
    """IAM rejects any character outside Latin-1 printable — notably the em
    dash this codebase uses freely in prose. CloudFormation only finds out
    mid-deploy and rolls the whole stack back (run 31216080066)."""
    offenders = []
    # ManagedPolicy as well as Role. IAM applies the same rule to both
    # descriptions, and the version of this test that checked only roles would
    # have passed a managed policy straight into the mid-deploy rollback it
    # exists to prevent — PORTH-586 added one and it was clean by luck.
    for name, resource in resources.items():
        if resource.get("Type") not in ("AWS::IAM::Role", "AWS::IAM::ManagedPolicy"):
            continue
        description = resource["Properties"].get("Description")
        if isinstance(description, str) and not LATIN1_PRINTABLE.match(description):
            bad = sorted({hex(ord(c)) for c in description if not LATIN1_PRINTABLE.match(c)})
            offenders.append(f"{name}: illegal {bad}")

    assert offenders == []
