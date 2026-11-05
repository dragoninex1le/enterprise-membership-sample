"""`bootstrap`, `reset` and `prune` on `porth` (PRF-20, contract 1.1), and `reset` on `porth-session`.

The slot is built the way porth-dau came to be: EMS's Porth install (the real script, porth_install),
plus a consuming app's own grant registered at deploy - that is the install. `bootstrap` captures it.
Then everything a test could do on top: a tenant the old qa-tools testbed seeder wrote (row shapes
copied from infra/qa-tools/src/seed/handler.py), a fixture prawf seeded itself, users, a change to the
platform tenant's IdP config. `reset` must remove all of it and leave the captured rows exactly,
never reach into another slot, and let the same seed through again afterwards.
"""
import gzip
import json

import boto3
import pytest

from test_porth_tenant import AUDIT, ORG_ID, SLOT, SNAPSHOTS, TABLES, call, porth, signed  # noqa: F401 - porth is a fixture
from porth_install import APP_GRANT, install, role_id, slot_rows

import snapshot  # noqa: E402 - on the path through test_adapter

VERSION = "0.3.1+ems.4f2a9c1"
OTHER = "porth-sample"

LEGACY_ORG = "5d0c9a8e-31f2-4c5b-9e7a-2b6f1d4c8a90"
LEGACY_ROLE = "8e1f2a3b-4c5d-4e6f-8a9b-0c1d2e3f4a5b"
NOW = "2026-10-01T09:00:00+00:00"


def org_dataset(slug="ems", name="EMS", version="1.0.0"):
    return signed({"id": f"ems.org.{slug}", "version": version, "form": "enumerated",
                   "resources": [{"type": "porth.org", "alias": slug, "spec": {"name": name}}]})


def tenant_dataset(tenant_id, org, version="1.0.0"):
    return signed({"id": f"ems.tenant.{tenant_id}", "version": version, "form": "enumerated",
                   "resources": [{"type": "tenant", "alias": tenant_id, "spec": {
                       "display_name": f"{tenant_id} display", "attributes": {
                           "tenant_tier": "development", "org": org, "admin_role_source_key": "tenant-admin"}}}]})


def legacy_testbed(scope=SLOT, tenant_id="ems-test"):
    """What the qa-tools seeder writes for one tenant - find-or-create org, the tenant, its role and claim mapping."""
    res = boto3.resource("dynamodb")
    env = lambda base: f"ENV#{scope}#{base}"  # noqa: E731
    res.Table(TABLES["tenants"]).put_item(Item={
        "PK": env(f"ORG#{LEGACY_ORG}"), "SK": "METADATA", "gsi1pk": env("ORG_SLUG#ems"), "gsi1sk": "METADATA",
        "id": LEGACY_ORG, "name": "ems", "slug": "ems", "status": "active", "created_at": NOW, "updated_at": NOW})
    res.Table(TABLES["tenants"]).put_item(Item={
        "PK": env(f"TENANT#{tenant_id}"), "SK": "METADATA",
        "gsi1pk": env(f"ORG#{LEGACY_ORG}"), "gsi1sk": f"TENANT#{tenant_id}",
        "tenant_id": tenant_id, "org_id": LEGACY_ORG, "org_name": "ems", "display_name": "EMS Test Tenant",
        "tenant_tier": "development", "status": "active",
        "idp_config_override": {"issuer": "https://idp.synthetic.test/", "provider_org_id": "org_synthetic"},
        "admin_email": "admin@synthetic.test", "admin_password_secret": "porth/testbed/tenants/synthetic/password",
        "updated_at": NOW, "created_at": NOW})
    res.Table(TABLES["roles"]).put_item(Item={
        "pk": env(f"TENANT#{tenant_id}"), "sk": f"ROLE#{LEGACY_ROLE}", "id": LEGACY_ROLE, "tenant_id": tenant_id,
        "name": "tenant-admin", "is_system": True, "source_key": "tenant-admin",
        "description": "Tenant administrator (seeded by qa-tools)", "created_at": NOW, "updated_at": NOW})
    # The grant shape before PORTH-604, keyed by role alone - an old slot can still carry it.
    res.Table(TABLES["roles"]).put_item(Item={
        "pk": env(f"ROLE#{LEGACY_ROLE}"), "sk": "PERM#tenant.users.read", "permission_key": "tenant.users.read"})
    res.Table(TABLES["claims"]).put_item(Item={
        "PK": env(f"TENANT#{tenant_id}"), "SK": "VERSION#000001", "gsi1pk": env(f"TENANT#{tenant_id}"),
        "gsi1sk": "VERSION#000001", "id": "c1", "tenant_id": tenant_id, "version": 1, "compiled_hash": "x"})


def two_slots():
    boto3.client("ssm").put_parameter(Name="/prawf/adapter/slot-map", Type="String", Overwrite=True, Value=json.dumps(
        {"slots": {SLOT: {"environment_id": "ems-porth-dau", "environment_class": "disposable"},
                   OTHER: {"environment_id": "ems-porth-sample", "environment_class": "disposable"}}}))


def v11(verb, payload=None, entity="porth", run_id="run-1", dry_run=False, slot=SLOT):
    return call(verb, payload, run_id=run_id, dry_run=dry_run, entity=entity, contract="1.1", slot=slot)


def bootstrap(version=VERSION, slot=SLOT, **kw):
    return v11("bootstrap", {"installed_version": version}, run_id="run-boot", slot=slot, **kw)


def reset(entity="porth", confirm="disposable", dry_run=False, baseline=None, run_id="run-reset", **extra):
    payload = {} if confirm is None else {"confirm_environment_class": confirm}
    if entity == "porth" and baseline is not False:
        payload["baseline"] = baseline
    payload.update(extra)
    return v11("reset", payload, entity=entity, run_id=run_id, dry_run=dry_run)


@pytest.fixture
def installed(porth, monkeypatch):
    """porth-dau straight after a deploy: the install, and an app's own grant on platform-admin."""
    t = boto3.resource("dynamodb").Table(TABLES["tenants"])
    t.delete_item(Key={"PK": f"ENV#{SLOT}#TENANT#platform", "SK": "METADATA"})
    t.delete_item(Key={"PK": f"ENV#{SLOT}#ORG#{ORG_ID}", "SK": "METADATA"})
    install(monkeypatch)
    boto3.resource("dynamodb").Table(TABLES["roles"]).put_item(Item={
        "pk": f"ENV#{SLOT}#TENANT#platform#ROLE#{role_id()}", "sk": f"PERM#{APP_GRANT}",
        "permission_key": APP_GRANT, "role_id": role_id(), "tenant_id": "platform"})
    return porth


@pytest.fixture
def testbed(installed):
    """The install captured, then everything a run could add on top of it."""
    boot = bootstrap()
    assert boot["outcome"] == "ok", boot
    baseline = boot["results"][0]
    captured = slot_rows()
    legacy_testbed()
    assert call("seed", {"dataset": org_dataset("acme", "Acme")}, run_id="run-acme", entity="porth-org")["outcome"] == "ok"
    assert call("seed", {"dataset": tenant_dataset("acme-test", "acme")}, run_id="run-acme")["outcome"] == "ok"
    installed["published"]()  # drain the seed's events
    named = {"installed_version": baseline["installed_version"], "content_digest": baseline["content_digest"]}
    return {**installed, "baseline": named, "captured": captured}


def org_dataset(slug="ems", name="EMS", version="1.0.0"):
    return signed({"id": f"ems.org.{slug}", "version": version, "form": "enumerated",
                   "resources": [{"type": "porth.org", "alias": slug, "spec": {"name": name}}]})


def tenant_dataset(tenant_id, org, version="1.0.0"):
    return signed({"id": f"ems.tenant.{tenant_id}", "version": version, "form": "enumerated",
                   "resources": [{"type": "tenant", "alias": tenant_id, "spec": {
                       "display_name": f"{tenant_id} display", "attributes": {
                           "tenant_tier": "development", "org": org, "admin_role_source_key": "tenant-admin"}}}]})


def tenants_in(scope=SLOT):
    rows = boto3.resource("dynamodb").Table(TABLES["tenants"]).scan()["Items"]
    return {r["PK"].split("#TENANT#", 1)[1] for r in rows
            if r["PK"].startswith(f"ENV#{scope}#TENANT#") and r["SK"] == "METADATA"}


def stored(scope=SLOT):
    items = boto3.client("dynamodb").query(TableName=AUDIT, KeyConditionExpression="PK = :pk",
                                           ExpressionAttributeValues={":pk": {"S": f"ENV#{scope}#ENTITY#porth"}})["Items"]
    return {i["SK"]["S"] for i in items}


# ---------------------------------------------------------------- bootstrap: capture what the install left

def test_bootstrap_captures_the_slot_and_says_which_baseline_it_is(installed):
    response = bootstrap()
    assert response["outcome"] == "ok", response
    (result,) = response["results"]
    assert result["entity"] == "porth" and result["baseline_kind"] == "snapshot"
    assert result["installed_version"] == VERSION
    assert result["content_digest"].startswith("sha256:") and len(result["content_digest"]) == 71
    assert stored() == {f"BASELINE#{VERSION}#{result['content_digest']}"}
    assert response["environment"] == {"id": "ems-porth-dau", "slot": SLOT}


def test_bootstrap_holds_no_idea_of_what_an_install_contains(installed):
    """Nothing is checked or repaired: an install without its platform tenant is captured as it is."""
    boto3.resource("dynamodb").Table(TABLES["tenants"]).delete_item(
        Key={"PK": f"ENV#{SLOT}#TENANT#platform", "SK": "METADATA"})
    before = slot_rows()
    assert bootstrap()["outcome"] == "ok"
    assert slot_rows() == before, "bootstrap writes nothing to Porth's tables"


def test_the_hash_is_stable_on_an_untouched_install(installed):
    first, second = bootstrap()["results"][0], bootstrap()["results"][0]
    assert first["content_digest"] == second["content_digest"]
    assert len(stored()) == 1, "the same content under the same version is stored once"


def test_bootstrap_again_after_a_change_keeps_both_baselines(installed):
    first = bootstrap()["results"][0]["content_digest"]
    boto3.resource("dynamodb").Table(TABLES["tenants"]).update_item(
        Key={"PK": f"ENV#{SLOT}#TENANT#platform", "SK": "METADATA"},
        UpdateExpression="SET tenant_tier = :t", ExpressionAttributeValues={":t": "corrected"})
    second = bootstrap()["results"][0]["content_digest"]
    assert first != second
    assert stored() == {f"BASELINE#{VERSION}#{first}", f"BASELINE#{VERSION}#{second}"}


def test_bootstrap_needs_an_installed_version(installed):
    for payload in (None, {}, {"installed_version": "has/slash"}, {"installed_version": "has#hash"}):
        response = v11("bootstrap", payload)
        assert (response["outcome"], response["reason_code"]) == ("refused", "installed_version_required"), payload
    assert stored() == set()


def test_a_dry_run_bootstrap_hashes_and_stores_nothing(installed):
    response = bootstrap(dry_run=True)
    assert response["outcome"] == "ok" and response["results"][0]["content_digest"].startswith("sha256:")
    assert stored() == set()


def test_bootstrap_is_contract_1_1_only(installed):
    response = call("bootstrap", {"installed_version": VERSION}, entity="porth")
    assert (response["outcome"], response["reason_code"]) == ("refused", "version_incompatible")


def test_bootstrap_must_name_its_slot_even_on_a_one_slot_target(installed):
    response = call("bootstrap", {"installed_version": VERSION}, entity="porth", contract="1.1")
    assert (response["outcome"], response["reason_code"]) == ("refused", "slot_required")
    assert stored() == set()


def test_bootstrap_never_captures_another_slots_rows(installed, monkeypatch):
    two_slots()
    install(monkeypatch, scope=OTHER)
    ours = bootstrap()["results"][0]["content_digest"]
    install(monkeypatch, scope=OTHER)  # the other slot changes; ours does not
    boto3.resource("dynamodb").Table(TABLES["tenants"]).update_item(
        Key={"PK": f"ENV#{OTHER}#TENANT#platform", "SK": "METADATA"},
        UpdateExpression="SET tenant_tier = :t", ExpressionAttributeValues={":t": "changed"})
    assert bootstrap()["results"][0]["content_digest"] == ours
    assert stored(OTHER) == set()


def test_a_baseline_too_big_for_its_item_goes_to_the_bucket(installed, monkeypatch):
    monkeypatch.setattr(snapshot, "INLINE_LIMIT", 10)
    digest = bootstrap()["results"][0]["content_digest"]
    (item,) = boto3.client("dynamodb").query(TableName=AUDIT, KeyConditionExpression="PK = :pk",
                                             ExpressionAttributeValues={":pk": {"S": f"ENV#{SLOT}#ENTITY#porth"}})["Items"]
    assert "payload" not in item
    key = item["payload_ref"]["S"]
    assert key.startswith(f"{SLOT}/porth/{VERSION}/"), "under the slot, so the session can reach only its own"
    body = boto3.client("s3").get_object(Bucket=SNAPSHOTS, Key=key)["Body"].read()
    assert snapshot.digest(json.loads(gzip.decompress(body))) == digest


# ---------------------------------------------------------------- reset: back to exactly what was captured

def test_reset_leaves_exactly_what_was_bootstrapped(testbed):
    response = reset(baseline=testbed["baseline"])
    assert response["outcome"] == "ok", response
    assert slot_rows() == testbed["captured"], "row for row, attribute for attribute"
    assert tenants_in() == {"platform"}
    assert response["results"][0]["content_digest"] == testbed["baseline"]["content_digest"]


def test_reset_undoes_a_change_to_the_install_itself(testbed):
    """An IdP config set on the platform tenant by a seed or a test goes; a test that needs it seeds it again."""
    boto3.resource("dynamodb").Table(TABLES["tenants"]).update_item(
        Key={"PK": f"ENV#{SLOT}#TENANT#platform", "SK": "METADATA"},
        UpdateExpression="SET idp_config_override = :i", ExpressionAttributeValues={":i": {"issuer": "https://changed.test/"}})
    boto3.resource("dynamodb").Table(TABLES["roles"]).delete_item(
        Key={"pk": f"ENV#{SLOT}#TENANT#platform#ROLE#{role_id()}", "sk": f"PERM#{APP_GRANT}"})
    assert reset(baseline=testbed["baseline"], expected_current_digest="sha256:" + "0" * 64)["outcome"] == "ok"
    assert slot_rows() == testbed["captured"]


def test_the_live_state_is_not_consulted(testbed):
    response = reset(baseline=testbed["baseline"], expected_current_digest="sha256:" + "0" * 64)
    assert response["outcome"] == "ok"
    assert any("not checked" in m for m in response["diagnostics"]["messages"])


def test_after_reset_the_same_seed_goes_through_again(testbed):
    """Back to seeded is reset then seed: the seed entities' ledgers went with their rows."""
    before = call("seed", {"dataset": tenant_dataset("ems-test", "ems")}, run_id="run-before")
    assert (before["outcome"], before["reason_code"]) == ("refused", "dataset_conflict")
    reset(baseline=testbed["baseline"])
    assert call("seed", {"dataset": org_dataset("acme", "Acme")}, run_id="run-again", entity="porth-org")["results"][0]["outcome"] == "created"
    again = call("seed", {"dataset": tenant_dataset("acme-test", "acme")}, run_id="run-again")
    assert again["results"][0]["outcome"] == "created"


def test_reset_keeps_the_stored_baselines(testbed):
    reset(baseline=testbed["baseline"])
    name = f"BASELINE#{VERSION}#{testbed['baseline']['content_digest']}"
    assert stored() == {name}
    assert reset(baseline=testbed["baseline"])["outcome"] == "ok", "and so can reset again"
    assert slot_rows() == testbed["captured"]


def test_reset_announces_what_it_removed(testbed):
    add_user("acme-test", "u-acme")
    reset(baseline=testbed["baseline"])
    published = testbed["published"]()
    assert published.count("Tenant.deleted") == 2
    assert published.count("Organization.deleted") == 2
    assert published.count("User.deleted") == 1


def test_reset_removes_users_assignments_and_org_units_that_were_not_installed(testbed):
    add_user("acme-test", "u-acme"); add_user("platform", "u-platform")
    reset(baseline=testbed["baseline"])
    assert people() == (set(), set(), set())


def test_reset_never_touches_another_slot(testbed, monkeypatch):
    two_slots()
    legacy_testbed(scope=OTHER, tenant_id="sample-test")
    add_user("sample-test", "u-other", scope=OTHER)
    other = slot_rows(OTHER)
    reset(baseline=testbed["baseline"])
    assert slot_rows(OTHER) == other


def test_a_dry_run_says_what_would_change_and_changes_nothing(testbed):
    before = slot_rows()
    response = reset(baseline=testbed["baseline"], dry_run=True)
    assert response["outcome"] == "ok"
    assert slot_rows() == before
    assert response["diagnostics"]["messages"][0] == "dry run: nothing changed"
    assert any("tenants: remove" in m for m in response["diagnostics"]["messages"])


def test_reset_must_name_a_baseline(testbed):
    before = slot_rows()
    response = reset(baseline=False)
    assert (response["outcome"], response["reason_code"]) == ("refused", "installed_version_required")
    assert slot_rows() == before


def test_a_baseline_never_captured_is_snapshot_invalid(testbed):
    before = slot_rows()
    for named in ({**testbed["baseline"], "content_digest": "sha256:" + "1" * 64},
                  {**testbed["baseline"], "installed_version": "0.0.1"}):
        response = reset(baseline=named)
        assert (response["outcome"], response["reason_code"]) == ("failed", "snapshot_invalid")
    assert slot_rows() == before


def test_a_corrupt_baseline_is_caught_before_anything_is_written(testbed):
    key = {"PK": {"S": f"ENV#{SLOT}#ENTITY#porth"},
           "SK": {"S": f"BASELINE#{VERSION}#{testbed['baseline']['content_digest']}"}}
    item = boto3.client("dynamodb").get_item(TableName=AUDIT, Key=key)["Item"]
    content = json.loads(gzip.decompress(item["payload"]["B"]))
    content["tables"]["tenants"]["rows"].pop()
    boto3.client("dynamodb").update_item(TableName=AUDIT, Key=key, UpdateExpression="SET payload = :p",
                                         ExpressionAttributeValues={":p": {"B": gzip.compress(json.dumps(content).encode())}})
    before = slot_rows()
    response = reset(baseline=testbed["baseline"])
    assert (response["outcome"], response["reason_code"]) == ("failed", "snapshot_invalid")
    assert slot_rows() == before


def test_a_baseline_in_the_bucket_restores_too(installed, monkeypatch):
    monkeypatch.setattr(snapshot, "INLINE_LIMIT", 10)
    result = bootstrap()["results"][0]
    captured = slot_rows()
    legacy_testbed()
    named = {"installed_version": VERSION, "content_digest": result["content_digest"]}
    assert reset(baseline=named)["outcome"] == "ok"
    assert slot_rows() == captured


def test_reset_must_name_its_entity(testbed):
    response = v11("reset", {"confirm_environment_class": "disposable"}, entity=None)
    assert (response["outcome"], response["reason_code"]) == ("refused", "unknown_entity")


def test_the_seed_entities_no_longer_reset_one_by_one(testbed):
    for entity in ("porth-tenant", "porth-org", "porth-role", "porth-claim-mapping"):
        response = reset(entity=entity)
        assert (response["outcome"], response["reason_code"]) == ("unsupported", "not_implemented"), entity


@pytest.mark.parametrize("confirm", [None, "protected"])
def test_a_missing_or_wrong_belief_about_the_slot_is_refused(testbed, confirm):
    before = slot_rows()
    response = reset(confirm=confirm, baseline=testbed["baseline"])
    assert (response["outcome"], response["reason_code"]) == ("refused", "scope_violation")
    assert slot_rows() == before


def test_c8_a_protected_slot_refuses_reset_whatever_the_caller_says(testbed):
    boto3.client("ssm").put_parameter(Name="/prawf/adapter/slot-map", Type="String", Overwrite=True, Value=json.dumps(
        {"slots": {SLOT: {"environment_id": "ems-porth-dau", "environment_class": "protected"}}}))
    before = slot_rows()
    for confirm in ("protected", "disposable"):
        for entity in ("porth", "porth-session"):
            response = reset(entity=entity, confirm=confirm, baseline=testbed["baseline"])
            assert (response["outcome"], response["reason_code"]) == ("refused", "environment_protected")
    assert slot_rows() == before


# ---------------------------------------------------------------- prune: only what prawf names

def test_prune_removes_exactly_what_is_named(installed, monkeypatch):
    first = bootstrap()["results"][0]["content_digest"]
    tenants = boto3.resource("dynamodb").Table(TABLES["tenants"])
    tenants.update_item(Key={"PK": f"ENV#{SLOT}#TENANT#platform", "SK": "METADATA"},
                        UpdateExpression="SET tenant_tier = :t", ExpressionAttributeValues={":t": "a"})
    monkeypatch.setattr(snapshot, "INLINE_LIMIT", 10)  # this one overflows to the bucket
    second = bootstrap()["results"][0]["content_digest"]
    third = bootstrap(version="0.3.2")["results"][0]["content_digest"]
    assert len(stored()) == 3

    response = v11("prune", {"baselines": [{"installed_version": VERSION, "content_digest": second},
                                           {"installed_version": "0.2.0"}]})
    assert response["outcome"] == "ok", response
    assert [r["outcome"] for r in response["results"]] == ["removed", "unchanged"]
    assert stored() == {f"BASELINE#{VERSION}#{first}", f"BASELINE#0.3.2#{third}"}
    assert boto3.client("s3").list_objects_v2(Bucket=SNAPSHOTS, Prefix=f"{SLOT}/porth/{VERSION}/").get("KeyCount") == 0

    by_version = v11("prune", {"baselines": [{"installed_version": VERSION}]})
    assert [r["outcome"] for r in by_version["results"]] == ["removed"]
    assert stored() == {f"BASELINE#0.3.2#{third}"}
    again = v11("prune", {"baselines": [{"installed_version": VERSION}]})
    assert [r["outcome"] for r in again["results"]] == ["unchanged"]


def test_prune_needs_baselines_and_an_entity(installed):
    bootstrap()
    for payload in (None, {}, {"baselines": []}, {"baselines": [{}]}):
        response = v11("prune", payload)
        assert (response["outcome"], response["reason_code"]) == ("refused", "installed_version_required"), payload
    response = v11("prune", {"baselines": [{"installed_version": VERSION}]}, entity=None)
    assert (response["outcome"], response["reason_code"]) == ("refused", "unknown_entity")
    assert len(stored()) == 1


def test_prune_never_reaches_another_slot(installed, monkeypatch):
    two_slots()
    install(monkeypatch, scope=OTHER)
    bootstrap(); bootstrap(slot=OTHER)
    v11("prune", {"baselines": [{"installed_version": VERSION}]})
    assert stored() == set() and len(stored(OTHER)) == 1


# ---------------------------------------------------------------- people, as Porth writes them at login

def add_user(tenant_id, user_id, scope=SLOT, role_id="role-1"):
    """A user as Porth writes one at login, with a role assignment and an org unit beside it."""
    base = f"ENV#{scope}#TENANT#{tenant_id}"
    db = boto3.resource("dynamodb")
    db.Table(TABLES["users"]).put_item(Item={"PK": f"{base}#USER#{user_id}", "SK": "METADATA", "id": user_id, "tenant_id": tenant_id,
                                             "gsi3pk": base, "gsi3sk": f"USER#{user_id}"})
    db.Table(TABLES["roles"]).put_item(Item={"pk": f"{base}#USER#{user_id}", "sk": f"ROLE#{role_id}"})
    db.Table(TABLES["org_units"]).put_item(Item={"PK": base, "SK": f"ORG_UNIT#{user_id}"})


def people(scope=SLOT):
    db = boto3.resource("dynamodb")
    users = {i["PK"].split("#USER#")[1] for i in db.Table(TABLES["users"]).scan()["Items"] if i["PK"].startswith(f"ENV#{scope}#")}
    assignments = {i["pk"].split("#USER#")[1] for i in db.Table(TABLES["roles"]).scan()["Items"]
                   if i["pk"].startswith(f"ENV#{scope}#") and "#USER#" in i["pk"]}
    units = {i["SK"].removeprefix("ORG_UNIT#") for i in db.Table(TABLES["org_units"]).scan()["Items"] if i["PK"].startswith(f"ENV#{scope}#")}
    return users, assignments, units



# ---------------------------------------------------------------- sessions, an entity in its own right

def add_sessions(*ids):
    table = boto3.resource("dynamodb").Table(TABLES["sessions"])
    for i in ids:
        table.put_item(Item={"pk": i, "environment": "porth-sample", "access_token": "a-token"})


def sessions():
    return {i["pk"] for i in boto3.resource("dynamodb").Table(TABLES["sessions"]).scan()["Items"]}


def test_resetting_sessions_clears_the_whole_table_and_nothing_else(testbed):
    add_sessions("s1", "s2")
    before = slot_rows()
    response = reset("porth-session")
    assert response["outcome"] == "ok", response
    assert sessions() == set()
    assert slot_rows() == before, "C16: resetting one entity leaves the others alone"
    messages = " ".join(response["diagnostics"]["messages"])
    assert "removed 2 session(s)" in messages and "every environment" in messages


def test_resetting_sessions_works_in_contract_1_0_too(testbed):
    add_sessions("s1")
    response = call("reset", {"confirm_environment_class": "disposable"}, entity="porth-session")
    assert response["outcome"] == "ok" and sessions() == set()


def test_a_dry_run_counts_sessions_and_removes_none_and_never_shows_a_token(testbed):
    add_sessions("s1", "s2")
    response = reset("porth-session", dry_run=True)
    messages = " ".join(response["diagnostics"]["messages"])
    assert "would remove 2 session(s)" in messages and "a-token" not in str(response)
    assert sessions() == {"s1", "s2"}


def test_clearing_an_empty_sessions_table_is_ok(testbed):
    response = reset("porth-session")
    assert response["outcome"] == "ok" and "removed 0 session(s)" in " ".join(response["diagnostics"]["messages"])
