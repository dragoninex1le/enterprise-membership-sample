"""`seed` and `teardown` on porth-org - the porth-org ruling, Option A (2026-10-23). Through the real
handler and the real porth-common 0.0.9 on moto, with the same slot fixture as porth-tenant."""
import boto3
import pytest

from test_porth_tenant import SLOT, TABLES, call, ems_test, porth, repos, rows, signed  # noqa: F401 - porth is a fixture


def ems_org(version="1.0.0", slug="ems-fixtures", name="EMS Fixtures") -> dict:
    return signed({
        "id": "ems.org", "version": version, "form": "enumerated",
        "resources": [{"type": "porth.org", "alias": slug, "spec": {"name": name}}],
    })


def org_repo():
    from porth_common.providers.aws.repositories.organization_repo import OrganizationRepository
    return OrganizationRepository(TABLES["tenants"], boto3.resource("dynamodb"), environment=SLOT)


def test_seed_writes_the_org_row_porth_0_3_1_writes_and_porth_reads_it_back(porth):
    response = call("seed", {"dataset": ems_org()}, entity="porth-org")
    assert response["outcome"] == "ok", response
    (handle,) = response["results"]
    org = org_repo().get_by_slug("ems-fixtures")
    assert (org.name, org.slug, org.status) == ("EMS Fixtures", "ems-fixtures", "active")
    assert handle["id"] == org.id and handle["type"] == "porth.org"
    item = boto3.resource("dynamodb").Table(TABLES["tenants"]).get_item(
        Key={"PK": f"ENV#{SLOT}#ORG#{org.id}", "SK": "METADATA"})["Item"]
    assert set(item) == {"PK", "SK", "gsi1pk", "gsi1sk", "id", "name", "slug", "status", "created_at", "updated_at"}
    assert "Organization.created" in porth["published"]()


def test_a_tenant_seeds_into_the_seeded_org(porth):
    call("seed", {"dataset": ems_org()}, entity="porth-org")
    response = call("seed", {"dataset": ems_test(org="ems-fixtures")})
    assert response["outcome"] == "ok", response
    tenants, _, _ = repos()
    assert tenants.get_by_id("ems-test").org_name == "EMS Fixtures"


def test_teardown_with_no_entity_removes_tenants_before_their_org(porth):
    before = rows()
    call("seed", {"dataset": ems_org()}, entity="porth-org")
    call("seed", {"dataset": ems_test(org="ems-fixtures")})
    response = call("teardown", {"run_id": "run-seed-1"}, run_id="run-teardown-1", entity=None)
    assert response["outcome"] == "ok", response
    assert rows() == before


def test_an_org_with_tenants_is_not_torn_down_alone(porth):
    call("seed", {"dataset": ems_org()}, entity="porth-org")
    call("seed", {"dataset": ems_test(org="ems-fixtures")})
    response = call("teardown", {"run_id": "run-seed-1"}, run_id="run-teardown-1", entity="porth-org")
    assert (response["outcome"], response["reason_code"]) == ("refused", "dataset_conflict")
    assert org_repo().get_by_slug("ems-fixtures") is not None


def test_an_existing_slug_is_never_overwritten(porth):
    before = rows()
    response = call("seed", {"dataset": ems_org(slug="ems", name="Someone else's")}, entity="porth-org")
    assert (response["outcome"], response["reason_code"]) == ("refused", "dataset_conflict")
    assert rows() == before


def test_the_same_org_dataset_again_is_unchanged(porth):
    call("seed", {"dataset": ems_org()}, entity="porth-org")
    before = rows()
    response = call("seed", {"dataset": ems_org()}, run_id="run-seed-2", entity="porth-org")
    assert response["results"][0]["outcome"] == "unchanged"
    assert rows() == before


def test_a_dry_run_writes_no_org(porth):
    before = rows()
    response = call("seed", {"dataset": ems_org()}, dry_run=True, entity="porth-org")
    assert response["outcome"] == "ok" and "id" not in response["results"][0]
    assert rows() == before


@pytest.mark.parametrize("resource", [
    {"type": "porth.org", "alias": "Not A Slug", "spec": {"name": "x"}},
    {"type": "porth.org", "alias": "ok-slug", "spec": {}},
    {"type": "porth.org", "alias": "ok-slug", "spec": {"name": "x", "tier": "y"}},
])
def test_an_org_porth_could_not_hold_is_refused(porth, resource):
    before = rows()
    dataset = signed({"id": "ems.org", "version": "1.0.0", "form": "enumerated", "resources": [resource]})
    response = call("seed", {"dataset": dataset}, entity="porth-org")
    assert (response["outcome"], response["reason_code"]) == ("refused", "dataset_conflict")
    assert rows() == before
