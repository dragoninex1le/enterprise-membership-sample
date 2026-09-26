"""Static checks on template.yml — the IAM traps, pinned so they cannot come back quietly.

Each of these has cost a deploy somewhere in this system, or would have:

* **aws:SourceAccount** in a resource policy for a role principal denies every call (the key only
  exists for service-to-service requests). PROVISIONING-CONTRACT §1.1's own example carries it.
* **Scan through a LeadingKeys condition** reads every slot: ForAllValues over an absent key is true.
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


def test_nothing_ever_allows_scan(tpl):
    for _, st in _statements(tpl):
        if st["Effect"] == "Allow":
            assert not {"dynamodb:Scan", "dynamodb:*", "*"} & set(_actions(st)), st


def test_the_data_role_is_read_only_and_denies_scan(tpl):
    stmts = [st for n, st in _statements(tpl) if n == "DataRole" and "Service" not in str(st.get("Principal", ""))]
    allowed = {a for st in stmts if st["Effect"] == "Allow" for a in _actions(st) if a.startswith("dynamodb:")}
    denied = {a for st in stmts if st["Effect"] == "Deny" for a in _actions(st)}
    assert allowed == {"dynamodb:GetItem", "dynamodb:BatchGetItem", "dynamodb:Query", "dynamodb:DescribeTable"}
    assert "dynamodb:Scan" in denied


def test_porth_tables_are_named_never_wildcarded(raw):
    assert "table/porth-*" not in raw
    assert "table/*" not in raw


def test_the_cross_account_permission_is_off_unless_a_caller_is_named(tpl):
    perm = tpl["Resources"]["CallerInvokePermission"]
    assert perm["Condition"] == "HasCaller"
    assert perm["Properties"]["Principal"] == {"Ref": "CallerRoleArn"}
    assert tpl["Parameters"]["CallerRoleArn"]["Default"] == ""


def test_the_default_slot_map_is_single_slot_until_prf_19(tpl):
    import json
    default = json.loads(tpl["Parameters"]["SlotMap"]["Default"])
    assert len(default["slots"]) == 1, "a 1.0.0 caller cannot name a slot, and a multi-slot map refuses it"


def test_every_sid_is_alphanumeric(tpl):
    import re
    for _, st in _statements(tpl):
        if "Sid" in st:
            assert re.fullmatch(r"[A-Za-z0-9]+", st["Sid"]), st["Sid"]
