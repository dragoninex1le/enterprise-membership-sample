"""Static checks on template.yml — the IAM traps, pinned so they cannot come back quietly.

Each of these has cost a deploy somewhere in this system, or would have:

* **aws:SourceAccount** in a resource policy for a role principal denies every call (the key only
  exists for service-to-service requests). PROVISIONING-CONTRACT §1.1's own example carries it.
* **Scan through a LeadingKeys condition** reads every slot: ForAllValues over an absent key is true.
  So Scan is granted on the tenants table alone, for reset (PRF-14), and denied on everything else.
* **porth-* as a table wildcard** also matches the sample app's own table on main.
* **Non-ASCII** in an IAM description once rolled back the whole ffug stack.
"""
from pathlib import Path

import pytest
import yaml

TEMPLATE = Path(__file__).resolve().parents[1] / "template.yml"


class _CfnLoader(yaml.SafeLoader):
    pass


def _any_tag(loader, tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return {tag_suffix: loader.construct_scalar(node)}
    if isinstance(node, yaml.SequenceNode):
        return {tag_suffix: loader.construct_sequence(node, deep=True)}
    return {tag_suffix: loader.construct_mapping(node, deep=True)}


_CfnLoader.add_multi_constructor("!", _any_tag)


@pytest.fixture(scope="module")
def raw():
    return TEMPLATE.read_text("utf-8")


@pytest.fixture(scope="module")
def tpl(raw):
    return yaml.load(raw, Loader=_CfnLoader)  # noqa: S506 - SafeLoader subclass


def _statements(tpl):
    for name, res in tpl["Resources"].items():
        props = res.get("Properties", {})
        docs = [p["PolicyDocument"] for p in props.get("Policies", [])]
        if "PolicyDocument" in props:
            docs.append(props["PolicyDocument"])
        for doc in docs:
            for st in doc["Statement"]:
                yield name, st


def _actions(st):
    a = st["Action"]
    return a if isinstance(a, list) else [a]


def test_template_is_ascii(raw):
    assert raw.isascii()


def test_no_source_account_condition_anywhere(raw):
    assert "aws:SourceAccount" not in raw.replace("No aws:SourceAccount condition", "")


def test_the_function_is_named_for_its_role_not_its_slot(tpl):
    fn = tpl["Resources"]["AdapterFunction"]["Properties"]
    assert fn["FunctionName"] == "porth-provisioning-adapter"
    assert fn["Runtime"] == "python3.13"
    assert fn["Role"] == {"GetAtt": "ExecutionRole.Arn"}


def test_the_execution_role_has_no_data_access(tpl):
    for name, st in _statements(tpl):
        if name in ("ExecutionRole", "ExecutionRoleMayAssumeDataRole") and st["Effect"] == "Allow":
            assert not any(a.startswith("dynamodb:") for a in _actions(st)), st


def test_only_the_tenants_table_may_ever_be_scanned(tpl):
    for name, st in _statements(tpl):
        if st["Effect"] != "Allow":
            continue
        assert not {"dynamodb:*", "*"} & set(_actions(st)), st
        if "dynamodb:Scan" in _actions(st):
            assert (name, st.get("Sid")) == ("DataRole", "ScanTheTenantsTable"), st
            assert _actions(st) == ["dynamodb:Scan"], "the scan grant carries nothing else"
            assert "table/${PorthTenantsTable}" in str(st["Resource"])
            assert "index" not in str(st["Resource"])
    (deny,) = [st for n, st in _statements(tpl) if n == "DataRole" and st.get("Sid") == "ScanNothingElse"]
    assert deny["Effect"] == "Deny" and _actions(deny) == ["dynamodb:Scan"]
    assert "table/${PorthTenantsTable}" in str(deny["NotResource"])


def test_the_data_role_reads_porth_writes_single_items_and_denies_partiql(tpl):
    stmts = [st for n, st in _statements(tpl) if n == "DataRole" and "Service" not in str(st.get("Principal", ""))]
    allowed = {a for st in stmts if st["Effect"] == "Allow" for a in _actions(st) if a.startswith("dynamodb:")}
    denied = {a for st in stmts if st["Effect"] == "Deny" for a in _actions(st)}
    assert allowed == {"dynamodb:GetItem", "dynamodb:BatchGetItem", "dynamodb:Query", "dynamodb:DescribeTable",
                       "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:Scan"}
    assert not any(a.startswith(("dynamodb:BatchWrite", "dynamodb:Transact")) for a in allowed)
    assert {"dynamodb:Scan", "dynamodb:PartiQLSelect", "dynamodb:ExecuteStatement"} <= denied


def test_the_data_role_writes_porths_four_tables_and_no_index(tpl):
    (writes,) = [st for n, st in _statements(tpl) if n == "DataRole" and st.get("Sid") == "WritePorthTables"]
    tables = {str(r) for r in writes["Resource"]}
    assert len(tables) == 4
    assert any("ClaimMapping" in t for t in tables), "bootstrap writes the platform claim mapping; reset removes others"
    assert not any("index" in t for t in tables), "writes go to tables; indexes are read"


def test_the_execution_role_reads_the_install_auth_record_and_writes_no_parameter(tpl):
    (auth,) = [st for n, st in _statements(tpl) if n == "ExecutionRole" and st.get("Sid") == "ReadPorthAuth"]
    assert _actions(auth) == ["ssm:GetParameter"]
    assert str(auth["Resource"]).rstrip("'}").endswith(":parameter/porth/auth")
    assert not any(a.startswith("ssm:Put") or a.startswith("ssm:Delete") for _, st in _statements(tpl) for a in _actions(st))


def test_the_data_role_publishes_on_porths_bus_and_no_other(tpl):
    (events,) = [st for n, st in _statements(tpl) if n == "DataRole" and st.get("Sid") == "PorthEventsOnly"]
    assert _actions(events) == ["events:PutEvents"]
    assert "event-bus/${PorthEventBus}" in str(events["Resource"])
    fn = tpl["Resources"]["AdapterFunction"]["Properties"]["Environment"]["Variables"]
    assert fn["PORTH_EVENT_BUS"] == {"Ref": "PorthEventBus"}, "porth-common's default bus is not Porth's"


def test_porth_tables_are_named_never_wildcarded(raw):
    assert "table/porth-*" not in raw
    assert "table/*" not in raw


def test_the_cross_account_permission_is_off_unless_a_caller_is_named(tpl):
    perm = tpl["Resources"]["CallerInvokePermission"]
    assert perm["Condition"] == "HasCaller"
    assert perm["Properties"]["Principal"] == {"Ref": "CallerRoleArn"}
    assert tpl["Parameters"]["CallerRoleArn"]["Default"] == ""
    off = tpl["Conditions"]["HasCaller"]["Not"][0]["Or"]
    assert {"Equals": [{"Ref": "CallerRoleArn"}, ""]} in off
    assert {"Equals": [{"Ref": "CallerRoleArn"}, "none"]} in off, "the deploy's release pass"


def test_the_deploy_releases_the_caller_grant_before_granting_it():
    wf = (TEMPLATE.parents[2] / ".github/workflows/deploy-provisioning-adapter.yml").read_text("utf-8")
    release, grant = wf.index('deploy "CallerRoleArn=none"'), wf.index('deploy "${CALLER_ARG[@]}"')
    assert release < grant, "the stale grant must go before a fresh one can be added"
    assert "CallerBinding" not in wf


def test_the_default_slot_map_is_single_slot_until_prf_19(tpl):
    import json
    default = json.loads(tpl["Parameters"]["SlotMap"]["Default"])
    assert len(default["slots"]) == 1, "a 1.0.0 caller cannot name a slot, and a multi-slot map refuses it"


def test_every_sid_is_alphanumeric(tpl):
    import re
    for _, st in _statements(tpl):
        if "Sid" in st:
            assert re.fullmatch(r"[A-Za-z0-9]+", st["Sid"]), st["Sid"]
