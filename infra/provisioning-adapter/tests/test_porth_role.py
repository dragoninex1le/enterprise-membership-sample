"""`seed` and `teardown` on porth-role (PRF-18): an arranged role, such as `no-access` for a denial test.

What the denial test needs from the data is a role a user can hold that grants nothing. So the tests
assert exactly that through Porth's own repository - the role exists, answers to its claim value, is
not a system role (so reset can take it), and holds no grants.
"""
import boto3

from test_porth_tenant import AUDIT, SLOT, TABLES, call, ems_test, porth, signed  # noqa: F401 - porth is a fixture


def no_access(tenant="ems-test", version="1.0.0", **spec):
    return signed({"id": f"ems.role.{tenant}.no-access", "version": version, "form": "enumerated",
                   "resources": [{"type": "porth.role", "alias": "no-access", "spec": {
                       "tenant": tenant, "source_key": "no-access", "description": "Holds nothing - for denial tests",
                       **spec}}]})


def roles():
    from porth_common.providers.aws.repositories.role_repo import RoleRepository
    return RoleRepository(TABLES["roles"], boto3.resource("dynamodb"), environment=SLOT)


def seed_tenant_then_role(run_id="run-seed-1"):
    assert call("seed", {"dataset": ems_test()}, run_id=run_id)["outcome"] == "ok"
    return call("seed", {"dataset": no_access()}, run_id=run_id, entity="porth-role")


def test_no_access_is_a_role_a_user_can_hold_that_grants_nothing(porth):
    response = seed_tenant_then_role()
    assert response["outcome"] == "ok", response
    (handle,) = response["results"]
    assert (handle["type"], handle["alias"], handle["outcome"]) == ("porth.role", "no-access", "created")
    role = next(r for r in roles().list_roles("ems-test") if r.name == "no-access")
    assert (role.source_key, role.is_system) == ("no-access", False)
    assert roles().get_role_permissions("ems-test", role.id) == [], "no grants - the denial test's premise"


def test_a_seeded_role_is_one_reset_takes_and_tenant_admin_survives(porth):
    seed_tenant_then_role()
    call("reset", {"confirm_environment_class": "disposable"}, run_id="run-reset", entity="porth-role")
    assert sorted(r.name for r in roles().list_roles("ems-test")) == ["tenant-admin"]


def test_grants_are_refused_a_seeded_role_holds_none(porth):
    call("seed", {"dataset": ems_test()})
    response = call("seed", {"dataset": no_access(permissions=["ar.read"])}, entity="porth-role")
    assert (response["outcome"], response["reason_code"]) == ("refused", "dataset_conflict")


def test_a_name_or_claim_value_already_in_use_is_refused(porth):
    call("seed", {"dataset": ems_test()})
    taken = signed({"id": "ems.role.clash", "version": "1.0.0", "form": "enumerated",
                    "resources": [{"type": "porth.role", "alias": "other", "spec": {"tenant": "ems-test", "source_key": "tenant-admin"}}]})
    response = call("seed", {"dataset": taken}, entity="porth-role")
    assert (response["outcome"], response["reason_code"]) == ("refused", "dataset_conflict")


def test_a_tenant_that_does_not_exist_is_refused(porth):
    response = call("seed", {"dataset": no_access()}, entity="porth-role")
    assert (response["outcome"], response["reason_code"]) == ("refused", "dataset_conflict")
    assert "seed porth-tenant first" in response["diagnostics"]["messages"][0]


def test_the_same_dataset_again_is_unchanged_and_a_dry_run_writes_nothing(porth):
    call("seed", {"dataset": ems_test()})
    dry = call("seed", {"dataset": no_access()}, dry_run=True, entity="porth-role")
    assert dry["results"][0]["outcome"] == "created"
    assert [r.name for r in roles().list_roles("ems-test")] == ["tenant-admin"]
    call("seed", {"dataset": no_access()}, entity="porth-role")
    again = call("seed", {"dataset": no_access()}, run_id="run-seed-2", entity="porth-role")
    assert again["results"][0]["outcome"] == "unchanged"


def test_teardown_with_no_entity_removes_the_role_before_its_tenant_and_leaves_nothing(porth):
    seed_tenant_then_role()
    response = call("teardown", {"run_id": "run-seed-1"}, run_id="run-teardown-1", entity=None)
    assert response["outcome"] == "ok", response
    assert roles().list_roles("ems-test") == []
    assert boto3.resource("dynamodb").Table(AUDIT).scan()["Items"] == []
