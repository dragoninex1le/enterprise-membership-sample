"""Static checks on bootstrap.yml - the controls that stop the adapter pipeline being an escalation path.

The same properties as Components' infra/prawf-runner, for the same reason, plus the ones specific to a
role whose job is data access:
* every adapter role carries prawf-adapter-boundary (checked against template.yml);
* the execution role creates or grants to adapter roles ONLY with that boundary, never removes it;
* the boundary reaches Porth's four table families by name - never porth-*, which on main matches the
  sample app's own table - and denies Scan, which would read every slot.
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


def test_the_boundary_names_porth_tables_and_never_the_apps(boot):
    stmts = boot["PrawfAdapterBoundary"]["Properties"]["PolicyDocument"]["Statement"]
    tables = [r for st in stmts if st["Effect"] == "Allow" for r in resources(st) if ":table/" in r]
    families = sorted(r.rsplit(":table/", 1)[1] for r in tables)
    assert families == ["porth-claim-mapping-configs-*", "porth-permissions-*", "porth-roles-*", "porth-tenants-*"]
    assert not any(f in ("porth-*", "*") for f in families)


def test_the_boundary_denies_scan_and_holds_no_iam(boot):
    stmts = boot["PrawfAdapterBoundary"]["Properties"]["PolicyDocument"]["Statement"]
    allowed = {a for st in stmts if st["Effect"] == "Allow" for a in actions(st)}
    denied = {a for st in stmts if st["Effect"] == "Deny" for a in actions(st)}
    assert "dynamodb:Scan" not in allowed and "dynamodb:Scan" in denied
    assert not any(a.startswith("iam:") for a in allowed)


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


def test_everything_the_adapter_roles_use_is_inside_the_boundary(boot):
    """A permission a role holds but its boundary does not allow is silently denied at runtime. So
    every action the adapter's roles are granted in template.yml must be one the boundary permits -
    this is what fails first when a later slice adds a verb and forgets the bootstrap."""
    boundary = {a for st in boot["PrawfAdapterBoundary"]["Properties"]["PolicyDocument"]["Statement"]
                if st["Effect"] == "Allow" for a in actions(st)}
    tpl = load("template.yml")["Resources"]
    used = {}
    for name in ("ExecutionRole", "DataRole", "ExecutionRoleMayAssumeDataRole"):
        for st in statements(tpl[name]):
            if st["Effect"] == "Allow" and "Principal" not in st:
                for a in actions(st):
                    used.setdefault(a, name)
    outside = {a: role for a, role in used.items() if a not in boundary}
    assert not outside, f"granted but not inside prawf-adapter-boundary (denied at runtime): {outside}"

