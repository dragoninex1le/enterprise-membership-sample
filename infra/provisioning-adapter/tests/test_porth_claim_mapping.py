"""`seed` and `teardown` on porth-claim-mapping (PRF-13), on porth-common 0.0.9 over moto.

The proof that matters is the last link of sign-in: the authorizer loads the tenant's latest claim
mapping and runs its compiled source to turn the token's roles claim into Porth role ids. So the
tests run the seeded mapping exactly that way - Porth's repository, then Porth's claim-mapping cache
- and assert a token carrying `tenant-admin` resolves to the tenant-admin role.
"""
import boto3

from test_porth_tenant import AUDIT, SLOT, TABLES, call, ems_test, porth, signed  # noqa: F401 - porth is a fixture

NAMESPACE = "https://api.synthetic.test/roles"


def mapping_source(namespace=NAMESPACE):
    """The default tenant mapping - the same shape the qa-tools seeder and the platform carry."""
    return {"schema_version": "2.0", "default_roles": [], "fields": [
        {"name": "roles", "source": namespace, "type": "collection", "required": False,
         "ops": [{"op": "resolve_roles"}]}]}


def claims_dataset(tenant_id="ems-test", source=None, version="1.0.0"):
    return signed({"id": f"ems.claims.{tenant_id}", "version": version, "form": "enumerated",
                   "resources": [{"type": "porth.claim-mapping", "alias": tenant_id,
                                  "spec": {"mapping_source": source or mapping_source()}}]})


def seed_tenant_then_claims(run_id="run-seed-1"):
    assert call("seed", {"dataset": ems_test()}, run_id=run_id)["outcome"] == "ok"
    return call("seed", {"dataset": claims_dataset()}, run_id=run_id, entity="porth-claim-mapping")


def repo():
    from porth_common.providers.aws.repositories.claim_mapping_config_repo import ClaimMappingConfigRepository
    return ClaimMappingConfigRepository(TABLES["claims"], boto3.resource("dynamodb"), environment=SLOT)


def admin_role_id():
    from porth_common.providers.aws.repositories.role_repo import RoleRepository
    roles = RoleRepository(TABLES["roles"], boto3.resource("dynamodb"), environment=SLOT)
    return next(r.id for r in roles.list_roles("ems-test") if r.name == "tenant-admin")


def test_the_seeded_mapping_resolves_a_tokens_tenant_admin_claim_to_the_role(porth):
    response = seed_tenant_then_claims()
    assert response["outcome"] == "ok", response
    (handle,) = response["results"]
    assert (handle["type"], handle["alias"], handle["outcome"]) == ("porth.claim-mapping", "ems-test", "created")

    from porth_common.services import claim_mapping_cache
    latest = repo().get_latest("ems-test")
    assert latest.version == 1
    mapped = claim_mapping_cache.load_and_cache("ems-test", latest.compiled_hash, latest.compiled_source)["map_claims"](
        {NAMESPACE: ["tenant-admin"]}, {"tenant-admin": admin_role_id()})
    assert mapped["roles"] == [admin_role_id()], "a signed-in tenant admin gets the tenant-admin role"


def test_it_publishes_the_event_porth_would(porth):
    seed_tenant_then_claims()
    assert "ClaimMappingConfig.created" in porth["published"]()


def test_the_same_dataset_again_is_unchanged(porth):
    seed_tenant_then_claims()
    again = call("seed", {"dataset": claims_dataset()}, run_id="run-seed-2", entity="porth-claim-mapping")
    assert again["results"][0]["outcome"] == "unchanged"
    assert repo().get_latest("ems-test").version == 1, "no second version"


def test_a_mapping_that_does_not_compile_is_refused_before_anything_is_written(porth):
    call("seed", {"dataset": ems_test()})
    broken = {"schema_version": "2.0", "fields": [{"name": "roles", "type": "nonsense"}]}
    response = call("seed", {"dataset": claims_dataset(source=broken)}, entity="porth-claim-mapping")
    assert (response["outcome"], response["reason_code"]) == ("refused", "dataset_conflict")
    assert repo().get_latest("ems-test") is None


def test_a_tenant_that_does_not_exist_is_refused(porth):
    response = call("seed", {"dataset": claims_dataset()}, entity="porth-claim-mapping")
    assert (response["outcome"], response["reason_code"]) == ("refused", "dataset_conflict")
    assert "seed porth-tenant first" in response["diagnostics"]["messages"][0]


def test_a_claim_mapping_this_dataset_did_not_write_is_never_added_to(porth):
    call("seed", {"dataset": ems_test()})
    repo().save(tenant_id="ems-test", mapping_source=mapping_source(), compiled_source="x", compiled_hash="y")
    response = call("seed", {"dataset": claims_dataset()}, entity="porth-claim-mapping")
    assert (response["outcome"], response["reason_code"]) == ("refused", "dataset_conflict")
    assert repo().get_latest("ems-test").version == 1


def test_a_dry_run_writes_nothing(porth):
    call("seed", {"dataset": ems_test()})
    response = call("seed", {"dataset": claims_dataset()}, dry_run=True, entity="porth-claim-mapping")
    assert response["results"][0]["outcome"] == "created"
    assert repo().get_latest("ems-test") is None


def test_teardown_with_no_entity_removes_the_mapping_before_its_tenant_and_leaves_nothing(porth):
    seed_tenant_then_claims()
    response = call("teardown", {"run_id": "run-seed-1"}, run_id="run-teardown-1", entity=None)
    assert response["outcome"] == "ok", response
    assert repo().get_latest("ems-test") is None
    claims = boto3.resource("dynamodb").Table(TABLES["claims"]).scan()["Items"]
    assert not any("ems-test" in i["PK"] for i in claims)
    assert boto3.resource("dynamodb").Table(AUDIT).scan()["Items"] == [], "the run's audit record goes too"
