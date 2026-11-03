"""`reset` (PRF-14) on a slot that looks like porth-dau did when the first live seed was refused.

The slot is built the way it came to be: EMS's Porth install (the real script, test_porth_platform),
then a tenant the old qa-tools testbed seeder wrote - its row shapes copied from
infra/qa-tools/src/seed/handler.py, so no gsi2, an IdP override, a tenant-admin role and a claim
mapping - then a fixture prawf seeded itself. Reset must clear both, leave the install's baseline row
for row, never reach into another slot, and let the refused seed through afterwards.
"""
import json

import boto3
import pytest

from test_porth_platform import APP_GRANT, NAMESPACE, _role_id, install, platform_rows
from test_porth_tenant import ORG_ID, SLOT, TABLES, call, ems_test, porth, signed  # noqa: F401 - porth is a fixture

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


@pytest.fixture
def testbed(porth, monkeypatch):
    """porth-dau as it stood: the install's baseline, the old seeder's ems-test, and a prawf fixture."""
    t = boto3.resource("dynamodb").Table(TABLES["tenants"])
    t.delete_item(Key={"PK": f"ENV#{SLOT}#TENANT#platform", "SK": "METADATA"})
    t.delete_item(Key={"PK": f"ENV#{SLOT}#ORG#{ORG_ID}", "SK": "METADATA"})
    install(monkeypatch)
    roles = boto3.resource("dynamodb").Table(TABLES["roles"])
    roles.put_item(Item={"pk": f"ENV#{SLOT}#TENANT#platform#ROLE#{_role_id()}", "sk": f"PERM#{APP_GRANT}",
                         "permission_key": APP_GRANT, "role_id": _role_id(), "tenant_id": "platform"})
    baseline = platform_rows(SLOT)
    legacy_testbed()
    assert call("seed", {"dataset": org_dataset("acme", "Acme")}, run_id="run-acme", entity="porth-org")["outcome"] == "ok"
    assert call("seed", {"dataset": tenant_dataset("acme-test", "acme")}, run_id="run-acme")["outcome"] == "ok"
    porth["published"]()  # drain the seed's events
    return {**porth, "baseline": baseline}


def reset(entity=None, confirm="disposable", dry_run=False, run_id="run-reset-1"):
    payload = {} if confirm is None else {"confirm_environment_class": confirm}
    return call("reset", payload, run_id=run_id, dry_run=dry_run, entity=entity)


def slot_rows(scope=SLOT):
    """Every row under a scope, raw."""
    out = set()
    for kind, name in TABLES.items():
        for item in boto3.resource("dynamodb").Table(name).scan()["Items"]:
            pk = item.get("PK") or item.get("pk")
            if pk.startswith(f"ENV#{scope}#"):
                out.add((kind, pk, item.get("SK") or item.get("sk")))
    return out


def tenants_in(scope=SLOT):
    return {pk.split("#TENANT#", 1)[1] for kind, pk, sk in slot_rows(scope)
            if kind == "tenants" and sk == "METADATA" and "#TENANT#" in pk}


# ---------------------------------------------------------------- the reset that unblocks the seed

def test_reset_leaves_exactly_the_installs_baseline(testbed):
    response = reset()
    assert response["outcome"] == "ok", response
    assert platform_rows(SLOT) == testbed["baseline"], "the baseline, row for row - the app's grant included"
    assert tenants_in() == {"platform"}
    messages = " ".join(response["diagnostics"]["messages"])
    assert "acme-test" in messages and "ems-test" in messages and "outside this adapter's grant" in messages


def test_after_reset_the_platform_is_still_bootstrapped(testbed):
    """C12: reset leaves the slot bootstrapped, not empty - bootstrap has nothing to do."""
    reset()
    again = call("bootstrap", None, run_id="run-boot-after", entity="porth-platform")
    assert {h["outcome"] for h in again["results"]} == {"unchanged"}


def test_after_reset_the_refused_seed_goes_through(testbed):
    """The live refusal of 2026-10-24: ems-test already existed, not prawf's. After reset it seeds."""
    before = call("seed", {"dataset": tenant_dataset("ems-test", "ems")}, run_id="run-before")
    assert (before["outcome"], before["reason_code"]) == ("refused", "dataset_conflict")
    reset()
    assert call("seed", {"dataset": org_dataset()}, run_id="run-live", entity="porth-org")["results"][0]["outcome"] == "created"
    seeded = call("seed", {"dataset": tenant_dataset("ems-test", "ems")}, run_id="run-live")
    assert seeded["results"][0]["outcome"] == "created"


def test_reset_publishes_the_deletions_porths_consumers_expect(testbed):
    reset()
    published = testbed["published"]()
    assert published.count("Tenant.deleted") == 2
    assert published.count("Organization.deleted") == 2


def test_prawfs_own_records_go_with_the_rows(testbed):
    reset()
    assert not any("PRAWF#" in pk for _, pk, _ in slot_rows())
    # So a seed after reset is judged afresh, not against a dataset that is gone.
    assert call("seed", {"dataset": org_dataset("acme", "Acme", version="2.0.0")}, run_id="run-2", entity="porth-org")["outcome"] == "ok"


# ---------------------------------------------------------------- safety

def test_a_dry_run_lists_what_would_go_and_removes_nothing(testbed):
    before = slot_rows()
    response = reset(dry_run=True)
    assert response["outcome"] == "ok"
    assert slot_rows() == before
    messages = response["diagnostics"]["messages"]
    assert messages[0] == "dry run: nothing removed"
    assert any("would remove tenant(s) ['acme-test', 'ems-test']" in m for m in messages), messages
    assert any("would remove organisation(s)" in m and "ems" in m and "acme" in m for m in messages), messages


def test_another_slots_rows_are_never_touched(testbed):
    legacy_testbed(scope="porth-sample", tenant_id="sample-test")
    other = slot_rows("porth-sample")
    reset()
    assert slot_rows("porth-sample") == other


@pytest.mark.parametrize("confirm, reason", [(None, "scope_violation"), ("protected", "scope_violation")])
def test_a_missing_or_wrong_belief_about_the_slot_is_refused(testbed, confirm, reason):
    before = slot_rows()
    response = reset(confirm=confirm)
    assert (response["outcome"], response["reason_code"]) == ("refused", reason)
    assert slot_rows() == before


def test_c8_a_protected_slot_refuses_reset_whatever_the_caller_says(testbed):
    boto3.client("ssm").put_parameter(Name="/prawf/adapter/slot-map", Type="String", Overwrite=True, Value=json.dumps(
        {"slots": {SLOT: {"environment_id": "ems-porth-dau", "environment_class": "protected"}}}))
    before = slot_rows()
    for confirm in ("protected", "disposable"):
        for entity in (None, "porth-tenant", "porth-org", "porth-claim-mapping"):
            response = reset(entity=entity, confirm=confirm)
            assert (response["outcome"], response["reason_code"]) == ("refused", "environment_protected")
    assert slot_rows() == before


def test_the_platform_cannot_be_reset(testbed):
    response = reset(entity="porth-platform")
    assert (response["outcome"], response["reason_code"]) == ("unsupported", "not_implemented")


def test_a_slot_with_no_platform_tenant_is_refused(porth):
    boto3.resource("dynamodb").Table(TABLES["tenants"]).delete_item(
        Key={"PK": f"ENV#{SLOT}#TENANT#platform", "SK": "METADATA"})
    response = reset()
    assert (response["outcome"], response["reason_code"]) == ("refused", "scope_violation")


# ---------------------------------------------------------------- one entity at a time (C16)

def test_c16_resetting_claim_mappings_leaves_tenants_and_orgs(testbed):
    tenants_before = {r for r in slot_rows() if r[0] in ("tenants", "roles", "permissions")}
    reset(entity="porth-claim-mapping")
    assert {r for r in slot_rows() if r[0] in ("tenants", "roles", "permissions")} == tenants_before
    claims = {pk for kind, pk, _ in slot_rows() if kind == "claims"}
    assert claims == {f"ENV#{SLOT}#TENANT#platform"}


def test_c16_resetting_tenants_leaves_orgs_and_claim_mappings(testbed):
    claims_before = {r for r in slot_rows() if r[0] == "claims"}
    reset(entity="porth-tenant")
    assert tenants_in() == {"platform"}
    assert {r for r in slot_rows() if r[0] == "claims"} == claims_before
    orgs = {pk for kind, pk, sk in slot_rows() if kind == "tenants" and "#ORG#" in pk}
    assert f"ENV#{SLOT}#ORG#{LEGACY_ORG}" in orgs
    roles = {pk for kind, pk, _ in slot_rows() if kind == "roles"}
    assert not any("ems-test" in pk or "acme-test" in pk or LEGACY_ROLE in pk for pk in roles), roles


def test_organisations_cannot_go_while_tenants_belong_to_them(testbed):
    before = slot_rows()
    response = reset(entity="porth-org")
    assert (response["outcome"], response["reason_code"]) == ("refused", "dataset_conflict")
    assert "reset porth-tenant first" in response["diagnostics"]["messages"][0]
    assert slot_rows() == before


def test_c11_two_datasets_across_successive_resets_both_seed(testbed):
    reset()
    call("seed", {"dataset": org_dataset()}, run_id="run-a", entity="porth-org")
    assert call("seed", {"dataset": tenant_dataset("ems-test", "ems")}, run_id="run-a")["outcome"] == "ok"
    reset(run_id="run-reset-2")
    call("seed", {"dataset": org_dataset(name="EMS Two", version="2.0.0")}, run_id="run-b", entity="porth-org")
    assert call("seed", {"dataset": tenant_dataset("ems-test", "ems", version="2.0.0")}, run_id="run-b")["outcome"] == "ok"


def test_reset_twice_is_ok_and_removes_nothing_more(testbed):
    reset()
    after = slot_rows()
    again = reset(run_id="run-reset-2")
    assert again["outcome"] == "ok"
    assert slot_rows() == after


# ---------------------------------------------------------------- arranged roles (PRF-14)

def _arrange_controller(tenant_id="acme-test"):
    """What Tier 2 does: a role created through the app after the seed, with grants."""
    from porth_common.providers.aws.repositories.role_repo import RoleRepository
    roles = RoleRepository(TABLES["roles"], boto3.resource("dynamodb"), environment=SLOT)
    role = roles.create_role(tenant_id=tenant_id, name="controller", source_key="controller", description="arranged")
    roles.set_role_permissions(role.id, ["tenant.users.read"], tenant_id)
    return roles, role


def _role_names(roles, tenant_id="acme-test"):
    return sorted(r.name for r in roles.list_roles(tenant_id))


def test_reset_of_roles_removes_the_arranged_role_and_keeps_the_seeded_baseline(testbed):
    """PRF-14 AC1: a seeded tenant, a role created afterwards, then reset - the extra role and its grants
    are gone; the baseline tenant-admin role and its grants remain."""
    roles, controller = _arrange_controller()
    admin = next(r for r in roles.list_roles("acme-test") if r.name == "tenant-admin")
    admin_grants = sorted(roles.get_role_permissions("acme-test", admin.id))
    permissions = {r for r in slot_rows() if r[0] == "permissions"}

    response = reset(entity="porth-role")
    assert response["outcome"] == "ok", response
    assert _role_names(roles) == ["tenant-admin"]
    assert roles.get_role_permissions("acme-test", controller.id) == [], "its grants go with it"
    assert sorted(roles.get_role_permissions("acme-test", admin.id)) == admin_grants
    assert tenants_in() >= {"acme-test", "ems-test"}, "C16: tenants are another entity's"
    assert {r for r in slot_rows() if r[0] == "permissions"} == permissions, "PORTH-609: permissions are never touched"
    assert "acme-test/controller" in " ".join(response["diagnostics"]["messages"])


def test_reset_of_roles_never_touches_the_platforms(testbed):
    from porth_common.providers.aws.repositories.role_repo import RoleRepository
    roles = RoleRepository(TABLES["roles"], boto3.resource("dynamodb"), environment=SLOT)
    roles.create_role(tenant_id="platform", name="platform-extra", source_key="platform-extra", description="x")
    reset(entity="porth-role")
    assert "platform-extra" in [r.name for r in roles.list_roles("platform")], "the platform is porth-platform's"


def test_a_dry_run_of_roles_lists_them_and_removes_nothing(testbed):
    roles, _ = _arrange_controller()
    response = reset(entity="porth-role", dry_run=True)
    assert any("would remove role(s) ['acme-test/controller']" in m for m in response["diagnostics"]["messages"])
    assert _role_names(roles) == ["controller", "tenant-admin"]


def test_a_full_reset_takes_arranged_roles_first_and_still_leaves_the_baseline(testbed):
    _arrange_controller()
    response = reset()
    assert response["outcome"] == "ok", response
    assert response["diagnostics"]["messages"][0].startswith("porth-role:")
    assert platform_rows(SLOT) == testbed["baseline"]
