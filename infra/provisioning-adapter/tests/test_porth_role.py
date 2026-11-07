"""`seed` and `teardown` on porth-role (PRF-18): the application's roles with the permissions they link
to, and arranged roles such as `no-access` for a denial test.

What the denial test needs from the data is a role a user can hold that grants nothing. So the tests
assert exactly that through Porth's own repository - the role exists, answers to its claim value, is
not a system role, and holds no grants. Reset of `porth` removes it with everything else seeded.
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
    return RoleRepository(TABLES["roles"], lambda: boto3.resource("dynamodb"), environment=SLOT)


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


def test_roles_no_longer_reset_one_by_one_reset_of_porth_takes_them(porth):
    seed_tenant_then_role()
    response = call("reset", {"confirm_environment_class": "disposable"}, run_id="run-reset", entity="porth-role")
    assert (response["outcome"], response["reason_code"]) == ("unsupported", "not_implemented")


#: What the sample app's deploy registers in the environment's catalogue - bootstrapped, never seeded.
APP_PERMISSIONS = ("dashboard.read", "ar.invoices.read", "ar.invoices.write", "ap.bills.read", "ap.bills.write",
                   "approvals.read", "approvals.write")


def bootstrap_app_permissions():
    """The install as the app's deploy leaves it: its permissions in the slot's catalogue."""
    from porth_common.providers.aws.repositories.permission_repo import PermissionRepository
    repo = PermissionRepository(TABLES["permissions"], lambda: boto3.resource("dynamodb"), environment=SLOT)
    for n, key in enumerate(APP_PERMISSIONS):
        repo.register(app_namespace="sample-app", key=key, display_name=key, category="Sample app",
                      sort_order=n, admin_role="tenant-admin")


def app_role(name, permissions, tenant="ems-test", version="1.0.0"):
    return signed({"id": f"ems.role.{tenant}.{name}", "version": version, "form": "enumerated",
                   "resources": [{"type": "porth.role", "alias": name, "spec": {
                       "tenant": tenant, "source_key": name, "permissions": permissions}}]})


def test_a_seeded_role_links_to_the_permissions_the_install_has(porth):
    bootstrap_app_permissions()
    call("seed", {"dataset": ems_test()})
    response = call("seed", {"dataset": app_role("ar-clerk", ["dashboard.read", "ar.invoices.write", "ar.invoices.read"])},
                    entity="porth-role")
    assert response["outcome"] == "ok", response
    role = next(r for r in roles().list_roles("ems-test") if r.name == "ar-clerk")
    assert (role.source_key, role.is_system) == ("ar-clerk", False)
    assert sorted(roles().get_role_permissions("ems-test", role.id)) == ["ar.invoices.read", "ar.invoices.write", "dashboard.read"]


def test_a_role_may_link_to_porths_own_tenant_permissions(porth):
    call("seed", {"dataset": ems_test()})
    response = call("seed", {"dataset": app_role("role-editor", ["tenant.roles.update"])}, entity="porth-role")
    assert response["outcome"] == "ok", response


def test_a_permission_the_slot_does_not_have_is_refused_and_nothing_is_written(porth):
    call("seed", {"dataset": ems_test()})
    response = call("seed", {"dataset": app_role("viewer", ["dashboard.read"])}, entity="porth-role")
    assert (response["outcome"], response["reason_code"]) == ("refused", "dataset_conflict")
    assert "dashboard.read" in response["diagnostics"]["messages"][0] and "bootstrapped" in response["diagnostics"]["messages"][0]
    assert [r.name for r in roles().list_roles("ems-test")] == ["tenant-admin"]


def test_a_platform_permission_is_never_granted_to_a_tenants_role(porth):
    bootstrap_app_permissions()
    call("seed", {"dataset": ems_test()})
    response = call("seed", {"dataset": app_role("sneaky", ["platform.tenants.read"])}, entity="porth-role")
    assert (response["outcome"], response["reason_code"]) == ("refused", "dataset_conflict")
    assert "platform" in response["diagnostics"]["messages"][0]


def test_permissions_must_be_a_list_of_distinct_keys(porth):
    bootstrap_app_permissions()
    call("seed", {"dataset": ems_test()})
    for bad in ("dashboard.read", ["dashboard.read", "dashboard.read"], [""]):
        response = call("seed", {"dataset": app_role("viewer", bad)}, entity="porth-role")
        assert (response["outcome"], response["reason_code"]) == ("refused", "dataset_conflict"), bad


def test_teardown_removes_the_role_and_its_grants(porth):
    bootstrap_app_permissions()
    call("seed", {"dataset": ems_test()}, run_id="run-t")
    call("seed", {"dataset": app_role("controller", list(APP_PERMISSIONS))}, run_id="run-t", entity="porth-role")
    role = next(r for r in roles().list_roles("ems-test") if r.name == "controller")
    call("teardown", {"run_id": "run-t"}, run_id="run-td", entity="porth-role")
    assert roles().get_role_permissions("ems-test", role.id) == []
    assert "controller" not in [r.name for r in roles().list_roles("ems-test")]


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
