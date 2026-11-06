"""Offline behavioural tests for the EMS provisioning adapter (PRF-9).

No AWS: SSM, STS, DynamoDB and CloudFormation are in-memory fakes. Every response is validated
against the real prawf schemas (`prawf-schemas`, the PRF-1 package) — the envelope with
`validate_contract_response`, the capabilities result with `validate_capabilities`. Passing these is
what "speaks the contract" means; the canary at the end proves the validator can actually fail.

What is pinned, and why:

* **C1 — declare only what is implemented.** The install verbs and each entity's verbs are exactly
  the implemented cells of the verb x entity matrix, checked by behaviour as well as by list.
* **C2 — every unimplemented verb is `unsupported`,** never an opaque failure. prawf skips it.
* **C15 — an unknown entity is `refused` with `unknown_entity`,** never a silent no-op.
* **R8 — one adapter per target, slot chosen per call, and no default slot.** Omission resolves only
  on a single-slot map. A slot is looked up, never interpolated, so `*` is refused, not matched.
* **Identity from the target's own map.** The slot must be in it, and what is reported is that
  entry, never the caller's words. Whether a slot is bootstrapped is prawf's record, not a guess here.
* **D5 — environment_class is the target's.** A request field claiming a class is ignored.
* **Isolation by IAM.** Data calls use credentials from an AssumeRole whose session policy admits
  one slot's keys, Scan on Porth's tables alone (bootstrap and reset of `porth`, PRF-20), and the
  snapshot bucket under the slot's own prefix; `ENV#porth-dau#*` must not match `ENV#porth-dau-probe#...`.
* **Contract 1.1** only when the caller asks for it: `environment` on every answer, a slot on every
  write, `baseline_kind` and `prune` in capabilities. Every answer, in either version, is validated
  against prawf-schemas 1.1, which holds both.
"""
import copy
import fnmatch
import json
import os
import sys
from pathlib import Path

import pytest
from prawf_schemas import validate_capabilities, validate_contract_request, validate_contract_response

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "adapter"))

import aws  # noqa: E402
import catalogue  # noqa: E402
import envelope  # noqa: E402
import handler  # noqa: E402
import slots  # noqa: E402

TENANTS = "porth-tenants-test"
SESSIONS = "porth-sessions-test"
PORTH_TABLES = {"PORTH_ROLES_TABLE": "porth-roles-test", "PORTH_PERMISSIONS_TABLE": "porth-permissions-test",
                "PORTH_CLAIM_MAPPING_CONFIGS_TABLE": "porth-claim-mapping-configs-test",
                "PORTH_USERS_TABLE": "porth-users-test", "PORTH_ORG_UNITS_TABLE": "porth-org-units-test"}
BUCKET = "prawf-adapter-snapshots-111111111111"
FAKE_CREDS = {"AccessKeyId": "FAKEKEYID", "SecretAccessKey": "FAKE-SECRET-VALUE", "SessionToken": "FAKE-TOKEN"}

ONE_SLOT = {"slots": {"porth-dau": {"environment_id": "ems-porth-dau", "environment_class": "disposable"}}}
TWO_SLOTS = {"slots": {
    "porth-dau": {"environment_id": "ems-porth-dau", "environment_class": "disposable"},
    "porth-sample": {"environment_id": "ems-porth-sample", "environment_class": "protected"},
}}

AGREED_ENTITIES = {
    "porth", "porth-org", "porth-tenant", "porth-claim-mapping",
    "porth-app-permission", "porth-role-grant", "porth-role", "porth-idp", "porth-session",
}
OTHER_VERBS = ["bootstrap", "seed", "reset", "ensure", "absent", "teardown", "status"]
#: An entity none of the verbs is implemented for, so every one of them is unsupported against it.
UNIMPLEMENTED_ENTITY = "porth-idp"


# ---------------------------------------------------------------- fakes

class FakeSSM:
    def __init__(self, value):
        self.value = value

    def get_parameter(self, Name):
        return {"Parameter": {"Name": Name, "Value": self.value}}


class FakeSTS:
    def __init__(self):
        self.calls = []

    def assume_role(self, **kwargs):
        self.calls.append(kwargs)
        return {"Credentials": dict(FAKE_CREDS)}


class FakeDynamo:
    def __init__(self, bootstrapped_scopes, fail=False):
        self.bootstrapped = set(bootstrapped_scopes)
        self.fail = fail
        self.reads = []

    def get_item(self, TableName, Key, **kwargs):
        if self.fail:
            raise RuntimeError("AccessDeniedException")
        pk, sk = Key["PK"]["S"], Key["SK"]["S"]
        self.reads.append((TableName, pk, sk))
        scope = pk.split("#")[1]
        if TableName == TENANTS and sk == "METADATA" and pk.endswith("#TENANT#platform") and scope in self.bootstrapped:
            return {"Item": {"PK": {"S": pk}}}
        return {}


class FakeCFN:
    def __init__(self, tags=None, fail=False):
        self.tags = tags if tags is not None else {"serverlessrepo:semanticVersion": "0.4.2"}
        self.fail = fail

    def describe_stacks(self, StackName):
        if self.fail:
            raise RuntimeError("AccessDenied")
        return {"Stacks": [{"StackName": StackName, "Tags": [{"Key": k, "Value": v} for k, v in self.tags.items()]}]}


@pytest.fixture
def world(monkeypatch):
    """A single-slot target, porth-dau bootstrapped, Porth at 0.4.2."""
    state = {
        "ssm": FakeSSM(json.dumps(ONE_SLOT)),
        "sts": FakeSTS(),
        "dynamodb": FakeDynamo({"porth-dau", "porth-sample"}),
        "cloudformation": FakeCFN(),
        "dynamodb_kwargs": [],
    }

    def client(service, **kwargs):
        if service == "dynamodb":
            state["dynamodb_kwargs"].append(kwargs)
        return state[service]

    monkeypatch.setattr(aws, "client", client)
    monkeypatch.setenv("SLOT_MAP_PARAMETER", "/prawf/adapter/slot-map")
    monkeypatch.setenv("DATA_ROLE_ARN", "arn:aws:iam::111111111111:role/porth-provisioning-adapter-DataRole-X")
    monkeypatch.setenv("PORTH_TENANTS_TABLE", TENANTS)
    monkeypatch.setenv("PORTH_SESSIONS_TABLE", SESSIONS)
    for k, v in PORTH_TABLES.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("PRAWF_SNAPSHOT_BUCKET", BUCKET)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("PORTH_STACK_NAME", "serverlessrepo-porth-components")
    monkeypatch.setenv("ADAPTER_VERSION", "test-build")
    return state


def call(**request):
    """Every answer, whatever was asked and in whichever version, must be one the schemas accept."""
    response = handler.handler(request, None)
    result = validate_contract_response(response)
    assert result.valid, (request, [str(e) for e in result.errors])
    return response


def capabilities(**extra):
    return call(contract_version="1.0.0", verb="capabilities", **extra)


def assert_speaks_the_contract(response):
    result = validate_contract_response(response)
    assert result.valid, [str(e) for e in result.errors]
    if response["outcome"] == "ok":
        assert "reason_code" not in response
    else:
        assert response["reason_code"]
        assert response["diagnostics"]["messages"], "a non-ok answer says why"


def assert_valid_capabilities(response):
    assert_speaks_the_contract(response)
    assert response["outcome"] == "ok"
    result = validate_capabilities(response["results"][0])
    assert result.valid, [str(e) for e in result.errors]
    return response["results"][0]


# ---------------------------------------------------------------- capabilities

def test_capabilities_validates_against_the_real_schemas(world):
    caps = assert_valid_capabilities(capabilities())
    assert caps["contract_versions"] == ["1.0.0"]
    assert caps["adapter_version"] == "test-build"


def test_exactly_the_implemented_cells_are_declared(world):
    caps = assert_valid_capabilities(capabilities())
    assert caps["verbs"] == ["capabilities", "seed", "reset", "teardown"]
    declared = {e["id"]: e["verbs"] for e in caps["entities"]}
    assert declared.pop("porth-tenant") == ["seed", "teardown"]
    assert declared.pop("porth-org") == ["seed", "teardown"]
    assert declared.pop("porth-claim-mapping") == ["seed", "teardown"]
    assert declared.pop("porth-role") == ["seed", "teardown"]
    assert declared.pop("porth-session") == ["reset"]
    assert declared.pop("porth") == [], "the snapshot baseline is contract 1.1: a 1.0 call cannot use it"
    assert caps["extension_types"] == ["porth.org", "porth.role", "porth.claim-mapping"]
    assert all(v == [] for v in declared.values()), declared
    assert caps["dataset_forms"] == ["enumerated"]
    assert caps["resource_types"] == ["tenant"]
    assert not any("baseline_kind" in e for e in caps["entities"]), "1.0 has no such field"


def test_in_1_1_porth_is_the_one_snapshot_entity(world):
    response = call(contract_version="1.1", verb="capabilities", slot="porth-dau")
    assert response["contract_version"] == "1.1" and response["outcome"] == "ok", response
    assert response["environment"] == {"id": "ems-porth-dau", "slot": "porth-dau"}
    caps = response["results"][0]
    result = validate_capabilities(caps)
    assert result.valid, [str(e) for e in result.errors]
    assert caps["contract_versions"] == ["1.0", "1.1"]
    assert caps["verbs"] == ["capabilities", "bootstrap", "seed", "reset", "teardown", "prune"]
    porth = next(e for e in caps["entities"] if e["id"] == "porth")
    assert porth["verbs"] == ["bootstrap", "reset", "prune"] and porth["baseline_kind"] == "snapshot"
    assert [e["id"] for e in caps["entities"] if "baseline_kind" in e] == ["porth"], "no state under two baselines"


@pytest.mark.parametrize("contract, slot", [("1.0.0", None), ("1.1", "porth-dau")])
def test_c1_every_declared_verb_is_actually_implemented(world, contract, slot):
    """C1, checked by behaviour rather than by a constant: nothing the adapter declares may answer
    `unsupported`. Stays correct as slices add verbs - and fails the moment one is declared early."""
    where = {"slot": slot} if slot else {}
    caps = call(contract_version=contract, verb="capabilities", **where)["results"][0]
    for verb in caps["verbs"]:
        assert call(contract_version=contract, verb=verb, **where)["outcome"] != "unsupported", verb
    for entity in caps["entities"]:
        for verb in entity["verbs"]:
            response = call(contract_version=contract, verb=verb, run={"run_id": "run-c1"}, entity=entity["id"], **where)
            assert response["outcome"] != "unsupported", (entity["id"], verb)


def test_the_catalogue_uses_the_agreed_names(world):
    caps = assert_valid_capabilities(capabilities())
    assert {e["id"] for e in caps["entities"]} == AGREED_ENTITIES
    assert catalogue.IDS == AGREED_ENTITIES


def test_the_idp_is_not_destructive_and_the_baseline_is(world):
    caps = assert_valid_capabilities(capabilities())
    destructive = {e["id"]: e["destructive"] for e in caps["entities"]}
    assert destructive["porth"] is True, "reset rewrites every row of the slot"
    assert destructive["porth-idp"] is False, "the adapter cannot reach it at all"


def test_every_ruled_out_verb_has_a_reason():
    for entity in catalogue.ENTITIES:
        assert all(reason.strip() for reason in entity.ruled_out.values()), entity.id
        assert not set(entity.verbs) & set(entity.ruled_out), entity.id


def test_candidate_version_comes_from_the_sar_stack_tag(world):
    caps = assert_valid_capabilities(capabilities())
    assert caps["environment"]["candidate_version"] == "0.4.2"


def test_a_missing_version_tag_is_omitted_and_explained(world):
    world["cloudformation"] = FakeCFN(tags={})
    response = capabilities()
    caps = assert_valid_capabilities(response)
    assert "candidate_version" not in caps["environment"]
    assert any("candidate_version unavailable" in m for m in response["diagnostics"]["messages"])


# ---------------------------------------------------------------- slots

def test_a_single_slot_map_resolves_an_omitted_slot(world):
    caps = assert_valid_capabilities(capabilities())
    assert caps["environment"] == {"id": "ems-porth-dau", "slot": "porth-dau", "candidate_version": "0.4.2"}


def test_a_multi_slot_map_refuses_an_omitted_slot(world):
    world["ssm"] = FakeSSM(json.dumps(TWO_SLOTS))
    response = capabilities()
    assert_speaks_the_contract(response)
    assert (response["outcome"], response["reason_code"]) == ("refused", "scope_violation")
    assert "no default slot" in response["diagnostics"]["messages"][0]


def test_a_named_slot_reports_that_slots_own_identity_and_class(world):
    world["ssm"] = FakeSSM(json.dumps(TWO_SLOTS))
    caps = assert_valid_capabilities(capabilities(slot="porth-sample"))
    assert caps["environment"]["id"] == "ems-porth-sample"
    assert caps["environment"]["slot"] == "porth-sample"
    assert caps["environment_class"] == "protected"


def test_an_unknown_slot_is_refused(world):
    response = capabilities(slot="porth-nope")
    assert_speaks_the_contract(response)
    assert (response["outcome"], response["reason_code"]) == ("refused", "scope_violation")


def test_in_1_1_the_slot_has_its_own_reason_codes(world):
    unknown = call(contract_version="1.1", verb="capabilities", slot="porth-nope")
    assert (unknown["outcome"], unknown["reason_code"]) == ("refused", "unknown_slot")
    assert "environment" not in unknown, "a slot that did not resolve has no environment to report"
    world["ssm"] = FakeSSM(json.dumps(TWO_SLOTS))
    missing = call(contract_version="1.1", verb="capabilities")
    assert (missing["outcome"], missing["reason_code"]) == ("refused", "slot_required")


@pytest.mark.parametrize("verb", ["bootstrap", "seed", "reset", "ensure", "absent", "teardown", "prune"])
def test_in_1_1_every_write_names_its_slot_even_on_a_one_slot_target(world, verb):
    response = call(contract_version="1.1", verb=verb, run={"run_id": "run-x"}, entity="porth-tenant")
    assert (response["outcome"], response["reason_code"]) == ("refused", "slot_required")
    assert world["sts"].calls == [], "refused before any credentials are issued"


def test_in_1_1_every_answer_says_where_it_acted(world):
    for verb in ("capabilities", "status", "seed"):
        response = call(contract_version="1.1", verb=verb, slot="porth-dau", run={"run_id": "run-x"}, entity="porth-idp")
        assert response["environment"] == {"id": "ems-porth-dau", "slot": "porth-dau"}, verb


@pytest.mark.parametrize("request_", [
    {"contract_version": "1.1", "slot": "porth-dau", "verb": "bootstrap", "entity": "porth",
     "run": {"run_id": "r"}, "payload": {"installed_version": "0.3.1"}},
    {"contract_version": "1.1", "slot": "porth-dau", "verb": "reset", "entity": "porth", "run": {"run_id": "r"},
     "payload": {"confirm_environment_class": "disposable",
                 "baseline": {"installed_version": "0.3.1", "content_digest": "sha256:" + "a" * 64}}},
    {"contract_version": "1.1", "slot": "porth-dau", "verb": "prune", "entity": "porth", "run": {"run_id": "r"},
     "payload": {"baselines": [{"installed_version": "0.3.1"}]}},
    {"contract_version": "1.1", "slot": "porth-dau", "verb": "reset", "entity": "porth-session", "run": {"run_id": "r"},
     "payload": {"confirm_environment_class": "disposable"}},
])
def test_the_1_1_requests_this_adapter_documents_are_ones_the_schemas_accept(request_):
    """What the README and the deploy proof send - prawf will build exactly these."""
    result = validate_contract_request(request_)
    assert result.valid, [str(e) for e in result.errors]


@pytest.mark.parametrize("slot", ["*", "porth-*", "porth-dau#*", "", 3])
def test_a_slot_is_looked_up_never_matched(world, slot):
    response = capabilities(slot=slot)
    assert_speaks_the_contract(response)
    assert response["outcome"] == "refused"
    assert world["sts"].calls == [], "no credentials are issued for a slot that did not resolve"


def test_capabilities_judges_no_install_and_reads_no_porth_data(world):
    """Whether a slot is bootstrapped is prawf's record of its baselines - not "the platform tenant row
    exists", which is a guess about what an install contains (Richard, 2026-11-05)."""
    caps = assert_valid_capabilities(capabilities())
    assert caps["environment"]["id"] == "ems-porth-dau"
    assert world["sts"].calls == [] and world["dynamodb"].reads == []


def test_environment_class_comes_from_the_target_not_the_caller(world):
    caps = assert_valid_capabilities(capabilities(environment_class="protected"))
    assert caps["environment_class"] == "disposable"


@pytest.mark.parametrize("raw", [
    "not json",
    json.dumps({"slots": {}}),
    json.dumps({"slots": {"Porth": ONE_SLOT["slots"]["porth-dau"]}}),
    json.dumps({"slots": {"porth-*": ONE_SLOT["slots"]["porth-dau"]}}),
    json.dumps({"slots": {"porth-dau": {**ONE_SLOT["slots"]["porth-dau"], "env_scope": "*"}}}),
    json.dumps({"slots": {"porth-dau": {**ONE_SLOT["slots"]["porth-dau"], "environment_class": "prod"}}}),
])
def test_a_broken_slot_map_fails_loudly(world, raw):
    world["ssm"] = FakeSSM(raw)
    response = capabilities()
    assert_speaks_the_contract(response)
    assert (response["outcome"], response["reason_code"]) == ("failed", "upstream_error")


# ---------------------------------------------------------------- isolation

def iam_string_like(pattern: str, value: str) -> bool:
    # IAM StringLike: * and ? wildcards, case-sensitive. Our patterns contain no brackets.
    return fnmatch.fnmatchcase(value, pattern)


def test_data_calls_run_on_a_one_slot_session(world):
    slots.data_session("porth-dau")
    (call_,) = world["sts"].calls
    assert call_["RoleArn"] == os.environ["DATA_ROLE_ARN"]
    assert call_["Policy"] == slots.session_policy("porth-dau")
    assert world["dynamodb_kwargs"][-1]["aws_access_key_id"] == "FAKEKEYID", "DynamoDB never sees the Lambda's own role"


def test_the_session_policy_admits_one_slot_and_not_its_prefix_extension(world):
    policy = json.loads(slots.session_policy("porth-dau"))
    (allow,) = [s for s in policy["Statement"] if s["Sid"] == "OneSlotOnly"]
    (pattern,) = allow["Condition"]["ForAllValues:StringLike"]["dynamodb:LeadingKeys"]
    assert iam_string_like(pattern, "ENV#porth-dau#TENANT#platform")
    assert not iam_string_like(pattern, "ENV#porth-sample#TENANT#platform")
    assert not iam_string_like(pattern, "ENV#porth-dau-probe#TENANT#platform")
    assert not iam_string_like(pattern, "TENANT#platform"), "an unscoped key is another slot's, not ours"


def test_the_session_policy_writes_single_items_in_one_slot_and_scans_only_porths_tables(world):
    policy = json.loads(slots.session_policy("porth-dau"))
    (one_slot,) = [s for s in policy["Statement"] if s["Sid"] == "OneSlotOnly"]
    assert set(one_slot["Action"]) == set(slots.READ_ACTIONS + slots.WRITE_ACTIONS)
    assert "dynamodb:LeadingKeys" in one_slot["Condition"]["ForAllValues:StringLike"], "every write is held to the slot"
    allowed = {a for s in policy["Statement"] if s["Effect"] == "Allow" for a in s["Action"]}
    denied = {a for s in policy["Statement"] if s["Effect"] == "Deny" for a in s["Action"]}
    assert allowed == set(slots.READ_ACTIONS + slots.WRITE_ACTIONS + slots.EVENT_ACTIONS
                          + slots.SNAPSHOT_ACTIONS + ("dynamodb:Scan",))
    assert not any(a.startswith(("dynamodb:BatchWrite", "dynamodb:Transact")) for a in allowed)
    assert {"dynamodb:PartiQLSelect", "dynamodb:ExecuteStatement"} <= denied

    # Scan: Porth's six data tables and the sessions table, exactly - not an index, not the audit
    # table. Sessions are the one thing reached beyond the slot, and only to find and delete rows.
    arn = "arn:aws:dynamodb:us-east-1:111111111111:table/{}"
    data = sorted(arn.format(t) for t in [TENANTS, *PORTH_TABLES.values()])
    scans = {s["Sid"]: s for s in policy["Statement"] if "dynamodb:Scan" in s["Action"]}
    assert set(scans) == {"ScanTheSlotsTables", "ClearTheSessionsTable"}
    assert scans["ScanTheSlotsTables"]["Action"] == ["dynamodb:Scan"]
    assert sorted(scans["ScanTheSlotsTables"]["Resource"]) == data
    clear = scans["ClearTheSessionsTable"]
    assert sorted(clear["Action"]) == ["dynamodb:DeleteItem", "dynamodb:DescribeTable", "dynamodb:Scan"]
    assert clear["Resource"] == arn.format(SESSIONS)
    assert not any("Condition" in s for s in scans.values())

    # The snapshot bucket: this slot's prefix, its delimiter included.
    (own,) = [s for s in policy["Statement"] if s["Sid"] == "OwnSnapshots"]
    assert own["Resource"] == f"arn:aws:s3:::{BUCKET}/porth-dau/*"
    assert not iam_string_like(own["Resource"].split(":::", 1)[1], f"{BUCKET}/porth-dau-probe/porth/x")


def test_the_session_policy_fits_sts_with_room_to_spare(world, monkeypatch):
    """AssumeRole refuses a session policy over 2,048 characters. Real names are longer than these."""
    for var in ("PORTH_TENANTS_TABLE", "PORTH_SESSIONS_TABLE", *PORTH_TABLES):
        monkeypatch.setenv(var, "porth-" + var.lower().replace("_", "-") + "-porth-components-production-x")
    assert len(slots.session_policy("porth-sample-long-name")) < 1900


@pytest.mark.parametrize("scope", ["*", "porth-*", "a#b", "Porth", ""])
def test_no_key_pattern_is_ever_built_from_an_unchecked_scope(scope):
    with pytest.raises(ValueError):
        slots.session_policy(scope)


def test_credentials_never_reach_a_response(world):
    responses = [capabilities(), call(contract_version="1.0.0", verb="seed", entity="porth-tenant")]
    blob = json.dumps(responses)
    for value in FAKE_CREDS.values():
        assert value not in blob


# ---------------------------------------------------------------- other verbs

@pytest.mark.parametrize("verb", OTHER_VERBS)
def test_every_unimplemented_verb_is_unsupported_not_failed(world, verb):
    response = call(contract_version="1.0.0", verb=verb, run={"run_id": "run-x"}, entity=UNIMPLEMENTED_ENTITY)
    assert_speaks_the_contract(response)
    assert (response["outcome"], response["reason_code"]) == ("unsupported", "not_implemented")


@pytest.mark.parametrize("verb", ["bootstrap", "seed", "ensure", "absent", "reset", "prune"])
def test_c17_omitting_the_entity_on_a_verb_that_writes_to_one_is_refused(world, verb):
    response = call(contract_version="1.0.0", verb=verb, run={"run_id": "run-x"})
    assert_speaks_the_contract(response)
    assert (response["outcome"], response["reason_code"]) == ("refused", "unknown_entity")


def test_an_unknown_verb_is_unsupported(world):
    response = call(contract_version="1.0.0", verb="obliterate")
    assert_speaks_the_contract(response)
    assert response["outcome"] == "unsupported"


def test_an_unknown_entity_is_refused_with_unknown_entity(world):
    response = call(contract_version="1.0.0", verb="seed", run={"run_id": "run-x"}, entity="porth-tables")
    assert_speaks_the_contract(response)
    assert (response["outcome"], response["reason_code"]) == ("refused", "unknown_entity")


def test_unknown_entity_outranks_unsupported(world):
    """Misaddressing is a precondition failure (abort); unimplemented is a skip. The stronger wins."""
    response = call(contract_version="1.0.0", verb="obliterate", entity="porth-tables")
    assert response["reason_code"] == "unknown_entity"


# ---------------------------------------------------------------- versions and envelopes

@pytest.mark.parametrize("requested,answered", [("1.0.0", "1.0.0"), ("1.4.2", "1.0.0"), ("1.1.0", "1.0.0")])
def test_a_three_part_caller_speaks_the_1_0_schemas_and_is_answered_in_1_0_0(world, requested, answered):
    response = call(contract_version=requested, verb="capabilities")
    assert_speaks_the_contract(response)
    assert response["contract_version"] == answered
    assert "environment" not in response


@pytest.mark.parametrize("requested,answered", [("1.0", "1.0"), ("1.1", "1.1"), ("1.9", "1.1")])
def test_a_two_part_caller_is_answered_in_the_highest_minor_we_share(world, requested, answered):
    response = call(contract_version=requested, verb="capabilities", slot="porth-dau")
    assert (response["outcome"], response["contract_version"]) == ("ok", answered)


@pytest.mark.parametrize("requested", ["2.0.0", "0.9.0", "2.0", "1", "latest", 1])
def test_no_common_version_is_refused_at_run_start(world, requested):
    response = call(contract_version=requested, verb="capabilities")
    assert_speaks_the_contract(response)
    assert (response["outcome"], response["reason_code"]) == ("refused", "version_incompatible")


@pytest.mark.parametrize("event", [None, "capabilities", [], {"verb": "capabilities"}, {"contract_version": "1.0.0"},
                                   {"body": json.dumps({"contract_version": "1.0.0", "verb": "capabilities"})}])
def test_anything_but_an_envelope_is_refused(world, event):
    """One shape. An API-Gateway-style `body` wrapper is refused, not unwrapped."""
    response = handler.handler(event, None)
    assert_speaks_the_contract(response)
    assert response["outcome"] == "refused"


# ---------------------------------------------------------------- canary

def test_the_validator_is_not_vacuous(world):
    """If these pass, the validator rejects what the contract forbids — so the tests above mean something."""
    caps = assert_valid_capabilities(capabilities())

    with_consumer = copy.deepcopy(caps)
    with_consumer["consumer"] = {"origin": "https://example.test"}
    result = validate_capabilities(with_consumer)
    assert not result.valid and "capabilities-consumer-removed" in {e.rule for e in result.errors}

    with_extra = copy.deepcopy(caps)
    with_extra["throughput"] = 10
    result = validate_capabilities(with_extra)
    assert not result.valid and "capabilities-closed-at-1-0-0" in {e.rule for e in result.errors}

    empty_verbs = copy.deepcopy(caps)
    empty_verbs["verbs"] = []
    assert not validate_capabilities(empty_verbs).valid, "an empty install verb list is not the honest answer - it is invalid"

    ok_with_reason = capabilities()
    ok_with_reason["reason_code"] = "not_implemented"
    assert not validate_contract_response(ok_with_reason).valid
