"""Static checks on bootstrap.yml - the controls that stop the adapter pipeline being an escalation path.

The same properties as Components' infra/prawf-runner, for the same reason, plus the ones specific to a
role whose job is data access:
* every adapter role carries prawf-adapter-boundary (checked against template.yml);
* the execution role creates or grants to adapter roles ONLY with that boundary, never removes it;
* the boundary is a deploy-time SCOPE, not the adapter's runtime policy (Richard, 2026-10-24): it names
  services and resource families - Porth's four table families by name, never porth-*, which on main
  matches the sample app's own table - data plane only, read-only parameters, nothing in IAM;
* everything template.yml grants the adapter's roles - action AND resource - is inside that scope, so a
  runtime change that would need a hand bootstrap deploy fails here, in its PR.
"""
import re
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parents[1]


class _Cfn(yaml.SafeLoader):
    pass


_Cfn.add_multi_constructor("!", lambda loader, tag, node: {
    tag: loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode)
    else loader.construct_sequence(node, deep=True) if isinstance(node, yaml.SequenceNode)
    else loader.construct_mapping(node, deep=True)
})


def load(name):
    return yaml.load((HERE / name).read_text("utf-8"), Loader=_Cfn)  # noqa: S506 - SafeLoader subclass


@pytest.fixture(scope="module")
def boot():
    return load("bootstrap.yml")["Resources"]


def statements(resource):
    props = resource["Properties"]
    docs = [p["PolicyDocument"] for p in props.get("Policies", [])]
    if "PolicyDocument" in props:
        docs.append(props["PolicyDocument"])
    return [st for d in docs for st in d["Statement"]]


def actions(st):
    a = st["Action"]
    return a if isinstance(a, list) else [a]


def _value(x):
    # The loader returns CloudFormation tags as {"Sub": "..."}; the string inside is what matters.
    return next(iter(x.values())) if isinstance(x, dict) and len(x) == 1 else x


def resources(st):
    r = st.get("Resource", [])
    return [str(_value(x)) for x in (r if isinstance(r, list) else [r])]


def test_ascii_alphanumeric_sids_no_source_account():
    text = (HERE / "bootstrap.yml").read_text("utf-8")
    assert text.isascii()
    for sid in re.findall(r"Sid:\s*(\S+)", text):
        assert re.fullmatch(r"[A-Za-z0-9]+", sid), sid
    assert "aws:SourceAccount" not in text


def test_every_adapter_role_carries_the_boundary():
    tpl = load("template.yml")["Resources"]
    for name in ("ExecutionRole", "DataRole"):
        assert "policy/prawf-adapter-boundary" in str(tpl[name]["Properties"].get("PermissionsBoundary")), name


def test_the_execution_role_grants_only_inside_the_boundary(boot):
    stmts = statements(boot["ExecutionRole"])
    granting = {"iam:CreateRole", "iam:PutRolePolicy", "iam:AttachRolePolicy", "iam:PutRolePermissionsBoundary"}
    seen = False
    for st in stmts:
        if st["Effect"] == "Allow" and granting & set(actions(st)):
            seen = True
            assert st["Condition"]["StringEquals"]["iam:PermissionsBoundary"] == {"Ref": "PrawfAdapterBoundary"}
    assert seen
    assert "iam:DeleteRolePermissionsBoundary" in {a for st in stmts if st["Effect"] == "Deny" for a in actions(st)}


def test_the_execution_role_touches_only_adapter_roles(boot):
    for st in statements(boot["ExecutionRole"]):
        if any(a.startswith("iam:") for a in actions(st)):
            assert all("role/porth-provisioning-adapter-*" in r for r in resources(st)), st["Sid"]
        assert "iam:*" not in actions(st) and "*" not in actions(st)


def test_role_passing_is_scoped_to_its_service(boot):
    for role in ("ExecutionRole", "DeployRole"):
        for st in statements(boot[role]):
            if "iam:PassRole" in actions(st):
                assert st["Condition"]["StringEquals"]["iam:PassedToService"] in (
                    "lambda.amazonaws.com", "cloudformation.amazonaws.com"), (role, st["Sid"])


def _boundary(boot):
    return boot["PrawfAdapterBoundary"]["Properties"]["PolicyDocument"]["Statement"]


def test_the_boundary_names_porth_tables_and_never_the_apps(boot):
    tables = [r for st in _boundary(boot) if st["Effect"] == "Allow" for r in resources(st) if ":table/" in r]
    families = sorted(r.rsplit(":table/", 1)[1] for r in tables)
    assert families == ["porth-claim-mapping-configs-*", "porth-permissions-*", "porth-roles-*", "porth-tenants-*"]
    assert not any(f in ("porth-*", "*") for f in families)


#: The services the scope may name, and of each the actions: data and reads, never administration.
SCOPE = {
    "logs": {"logs:CreateLogStream", "logs:PutLogEvents"},
    "ssm": {"ssm:GetParameter", "ssm:GetParameters"},
    "cloudformation": {"cloudformation:DescribeStacks"},
    "sts": {"sts:AssumeRole"},
    "events": {"events:PutEvents"},
    "dynamodb": {"dynamodb:DescribeTable", "dynamodb:GetItem", "dynamodb:BatchGetItem", "dynamodb:Query",
                 "dynamodb:Scan", "dynamodb:ConditionCheckItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
                 "dynamodb:DeleteItem", "dynamodb:BatchWriteItem"},
}


def test_the_boundary_is_a_deploy_scope_with_no_runtime_detail_and_no_iam(boot):
    stmts = _boundary(boot)
    assert all(st["Effect"] == "Allow" for st in stmts), "denies are runtime policy - template.yml holds them"
    for st in stmts:
        for a in actions(st):
            service = a.split(":", 1)[0]
            assert service in SCOPE and a in SCOPE[service], (st["Sid"], a)
        assert "Condition" not in st, f"{st['Sid']}: conditions are runtime policy"
    allowed = {a for st in stmts for a in actions(st)}
    assert not any(a.startswith(("iam:", "kms:")) or a.endswith("*") for a in allowed)
    assert not {"dynamodb:CreateTable", "dynamodb:UpdateTable", "dynamodb:DeleteTable"} & allowed


def test_the_boundary_reads_porths_and_the_adapters_parameters_and_writes_none(boot):
    params = sorted(r.rsplit(":parameter", 1)[1] for st in _boundary(boot)
                    for r in resources(st) if ":parameter" in r)
    assert params == ["/porth/*", "/prawf/adapter/*"]
    assert not any(a.startswith(("ssm:Put", "ssm:Delete")) for st in _boundary(boot) for a in actions(st))


def test_the_deploy_role_has_no_iam_power_beyond_passing_the_execution_role(boot):
    for st in statements(boot["DeployRole"]):
        if st["Effect"] == "Allow":
            assert [a for a in actions(st) if a.startswith("iam:")] in ([], ["iam:PassRole"]), st["Sid"]


def test_the_execution_role_can_read_the_lambda_code_and_nothing_more_of_s3(boot):
    """CloudFormation creates the function as the execution role, and Lambda reads the code from S3
    with that role's permissions - so it needs read on SAM's artifacts, and only read."""
    s3 = [st for st in statements(boot["ExecutionRole"]) if any(a.startswith("s3:") for a in actions(st))]
    assert s3, "no S3 read: the first deploy would fail fetching the code"
    for st in s3:
        assert set(actions(st)) <= {"s3:GetObject", "s3:GetObjectVersion"}, st["Sid"]
        assert all("samclisourcebucket-*/*" in r for r in resources(st)), st["Sid"]


#: What the deploy resolves template.yml's parameters to, near enough to test against the boundary.
_RESOLVED = {"AWS::Region": "us-east-1", "AWS::AccountId": "195950944420", "PorthStackName": "serverlessrepo-porth-components",
             "PorthTenantsTable": "porth-tenants-dev", "PorthRolesTable": "porth-roles-dev",
             "PorthPermissionsTable": "porth-permissions-dev", "PorthClaimMappingConfigsTable": "porth-claim-mapping-configs-dev",
             "PorthEventBus": "porth-events-dev"}


def _arn(x) -> str:
    """A template resource as the ARN it deploys to: !Sub resolved, !GetAtt DataRole.Arn as the role SAM names."""
    if isinstance(x, dict) and "GetAtt" in x:
        assert x["GetAtt"] in ("DataRole.Arn", "RunnerLogs.Arn"), x
        return "arn:aws:iam::195950944420:role/porth-provisioning-adapter-DataRole-ABC123"
    if isinstance(x, dict) and "Ref" in x:
        return "arn:aws:ssm:us-east-1:195950944420:parameter/prawf/adapter/slot-map"
    text = str(_value(x))
    return re.sub(r"\$\{([^}]+)\}", lambda m: _RESOLVED[m.group(1)], text)


def _iam_like(pattern: str, value: str) -> bool:
    return re.fullmatch(re.escape(pattern).replace(r"\*", ".*"), value) is not None


def test_everything_the_adapter_roles_use_is_inside_the_boundary(boot):
    """A permission a role holds but its boundary does not allow is silently denied at runtime. So
    every action the adapter's roles are granted in template.yml - and every resource it is granted on
    - must be one the boundary permits. This is what fails, in the PR, when a runtime change would
    need a bootstrap deploy: the fix is almost always in template.yml, not here."""
    scope = [(set(actions(st)), [_arn(r) for r in (st["Resource"] if isinstance(st["Resource"], list) else [st["Resource"]])])
             for st in _boundary(boot)]
    scope = [(acts, [re.sub(r"\$\{([^}]+)\}", lambda m: _RESOLVED[m.group(1)], r) for r in res]) for acts, res in scope]
    tpl = load("template.yml")["Resources"]
    outside = []
    for name in ("ExecutionRole", "DataRole", "ExecutionRoleMayAssumeDataRole"):
        for st in statements(tpl[name]):
            if st["Effect"] != "Allow" or "Principal" in st:
                continue
            res = st["Resource"] if isinstance(st["Resource"], list) else [st["Resource"]]
            for a in actions(st):
                for r in res:
                    arn = _arn(r)
                    if arn == "*" and a.startswith("events:"):
                        continue
                    if not any(a in acts and any(_iam_like(p, arn) for p in pats) for acts, pats in scope):
                        outside.append((name, st.get("Sid"), a, arn))
    assert not outside, f"granted but outside prawf-adapter-boundary (denied at runtime): {outside}"


def test_the_execution_role_can_expand_the_sam_transform(boot):
    """template.yml uses AWS::Serverless-2016-10-31, and with --role-arn the execution role is the one
    that expands it. Missing this, the very first change set fails before any resource exists."""
    found = [st for st in statements(boot["ExecutionRole"])
             if st["Effect"] == "Allow" and actions(st) == ["cloudformation:CreateChangeSet"]]
    assert found, "no CreateChangeSet on the SAM transform"
    assert all(r.endswith(":aws:transform/Serverless-2016-10-31") for st in found for r in resources(st))


def test_the_boundary_publishes_on_porths_bus_family_only(boot):
    """PRF-12: Porth's repositories raise if they cannot publish, so writing Porth's rows with Porth's
    code needs PutEvents - on Porth's buses (porth-events-{env}) and nowhere else."""
    events = [st for st in _boundary(boot) if any(a.startswith("events:") for a in actions(st))]
    (st,) = events
    assert actions(st) == ["events:PutEvents"]
    assert [_value(r) for r in resources(st)] == ["arn:aws:events:${AWS::Region}:${AWS::AccountId}:event-bus/porth-events-*"]


def test_the_deploy_role_reads_porth_common_and_nothing_else_of_codeartifact(boot):
    reads = [st for st in statements(boot["DeployRole"]) if "codeartifact:ReadFromRepository" in actions(st)]
    repos = {str(_value(r)).rsplit(":", 1)[-1] for st in reads for r in resources(st)}
    assert repos == {"domain/estyn-prawf", "repository/estyn-prawf/estyn-prawf-py", "domain/porth", "repository/porth/porth-py"}
    assert not any("Publish" in a or "Delete" in a for st in reads for a in actions(st)), "read, never publish"


def test_the_boundary_updates_in_place(boot):
    """An AWS::IAM::ManagedPolicy is REPLACED when its name, path or description changes - and with a
    fixed ManagedPolicyName the replacement collides with the policy it replaces ("already exists",
    2026-10-24). Its document changes in place. So these three are frozen; change only the document."""
    props = boot["PrawfAdapterBoundary"]["Properties"]
    assert props["ManagedPolicyName"] == "prawf-adapter-boundary"
    assert props["Description"] == "The most any provisioning-adapter role can ever do."
    assert "Path" not in props
