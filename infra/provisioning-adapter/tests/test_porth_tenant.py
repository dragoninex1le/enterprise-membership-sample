"""`seed` and `teardown` on porth-tenant (PRF-12, PRF-15), through the real handler and the real
porth-common 0.0.9 - the Porth EMS runs - against an in-memory AWS (moto).

Not fakes: the point of this slice is that the rows are exactly Porth's, and only Porth's own code
can say that. So the tests read every seeded row back through porth-common's repositories, and run
Porth's tenant directory scan, the one a bad row would empty. What moto cannot show is IAM - the
one-slot session policy is pinned in test_adapter.py, and the boundary in test_bootstrap.py.
"""
import copy
import hashlib
import json
import os

import boto3
import pytest
from moto import mock_aws
from prawf_schemas import validate_contract_response

from test_adapter import aws, handler  # noqa: F401 - the adapter's modules, on the path

SLOT = "porth-dau"
TABLES = {"tenants": "porth-tenants-dev", "roles": "porth-roles-dev", "permissions": "porth-permissions-dev",
          "claims": "porth-claim-mapping-configs-dev"}
AUDIT = "prawf-adapter-audit"  # prawf's own table - never one of Porth's
ORG_ID = "0b7d3e52-9a51-4bd4-8a1e-3f0c2d1e9a77"
#: The install's /porth/auth blob, as build_auth_blob.py writes it - synthetic values.
AUTH = {"issuer": "https://idp.synthetic.test/", "jwks_uri": "https://idp.synthetic.test/.well-known/jwks.json",
        "interactive_client_id": "synthetic-client", "audience": "https://api.synthetic.test", "protocol": "oidc"}


def signed(dataset: dict) -> dict:
    body = {k: v for k, v in dataset.items() if k != "digest"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {**body, "digest": "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()}


def ems_test(version="1.0.0", **attributes) -> dict:
    attrs = {"tenant_tier": "development", "org": "ems", "admin_role_source_key": "tenant-admin", **attributes}
    return signed({
        "id": "ems.ems-test-tenant", "version": version, "form": "enumerated",
        "resources": [{"type": "tenant", "alias": "ems-test",
                       "spec": {"display_name": "EMS Test Tenant", "attributes": attrs}}],
    })


def _table(client, name, pk, sk, gsis):
    attrs = {pk, sk} | {a for _, h, r in gsis for a in (h, r)}
    indexes = [{
        "IndexName": n, "Projection": {"ProjectionType": "ALL"},
        "KeySchema": [{"AttributeName": h, "KeyType": "HASH"}, {"AttributeName": r, "KeyType": "RANGE"}],
    } for n, h, r in gsis]
    client.create_table(
        TableName=name, BillingMode="PAY_PER_REQUEST",
        KeySchema=[{"AttributeName": pk, "KeyType": "HASH"}, {"AttributeName": sk, "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": a, "AttributeType": "S"} for a in sorted(attrs)],
        **({"GlobalSecondaryIndexes": indexes} if indexes else {}),
    )


@pytest.fixture
def porth(monkeypatch):
    """A Porth 0.3.1 slot: the tables, the event bus, the platform tenant and the `ems` org."""
    for k, v in {"AWS_DEFAULT_REGION": "us-east-1", "AWS_ACCESS_KEY_ID": "testing",
                 "AWS_SECRET_ACCESS_KEY": "testing", "AWS_SESSION_TOKEN": "testing"}.items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        ddb = boto3.client("dynamodb")
        _table(ddb, TABLES["tenants"], "PK", "SK", [("gsi1", "gsi1pk", "gsi1sk"), ("gsi2", "gsi2pk", "gsi2sk")])
        _table(ddb, TABLES["roles"], "pk", "sk", [("gsi1", "gsi1pk", "gsi1sk")])
        _table(ddb, TABLES["permissions"], "pk", "sk", [("gsi1", "gsi1pk", "gsi1sk")])
        _table(ddb, TABLES["claims"], "PK", "SK", [("gsi1", "gsi1pk", "gsi1sk")])
        _table(ddb, AUDIT, "PK", "SK", [])
        events = boto3.client("events")
        events.create_event_bus(Name="porth-events")
        sqs = boto3.client("sqs")
        queue = sqs.create_queue(QueueName="porth-events-tap")["QueueUrl"]
        queue_arn = sqs.get_queue_attributes(QueueUrl=queue, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
        events.put_rule(Name="tap", EventBusName="porth-events", EventPattern=json.dumps({"source": [{"prefix": ""}]}))
        events.put_targets(Rule="tap", EventBusName="porth-events", Targets=[{"Id": "q", "Arn": queue_arn}])
        boto3.client("ssm").put_parameter(Name="/prawf/adapter/slot-map", Type="String", Value=json.dumps(
            {"slots": {SLOT: {"environment_id": "ems-porth-dau", "environment_class": "disposable"}}}))
        boto3.client("ssm").put_parameter(Name="/porth/auth", Type="String", Value=json.dumps(AUTH))

        tenants = boto3.resource("dynamodb").Table(TABLES["tenants"])
        now = "2026-09-15T19:40:00+00:00"
        tenants.put_item(Item={"PK": f"ENV#{SLOT}#TENANT#platform", "SK": "METADATA", "tenant_id": "platform",
                               "org_id": ORG_ID, "display_name": "Platform", "tenant_tier": "production",
                               "status": "active", "role_type": "platform-admin", "created_at": now, "updated_at": now,
                               "gsi2pk": f"ENV#{SLOT}#TENANTS", "gsi2sk": "TENANT#platform"})
        tenants.put_item(Item={"PK": f"ENV#{SLOT}#ORG#{ORG_ID}", "SK": "METADATA", "gsi1pk": f"ENV#{SLOT}#ORG_SLUG#ems",
                               "gsi1sk": "METADATA", "id": ORG_ID, "name": "EMS", "slug": "ems", "status": "active",
                               "created_at": now, "updated_at": now})

        monkeypatch.setattr(aws, "client", lambda service, **kw: boto3.client(service, **kw))
        monkeypatch.setattr(aws, "resource", lambda service, **kw: boto3.resource(service, **kw))
        monkeypatch.setenv("SLOT_MAP_PARAMETER", "/prawf/adapter/slot-map")
        monkeypatch.setenv("DATA_ROLE_ARN", "arn:aws:iam::123456789012:role/porth-provisioning-adapter-DataRole-X")
        monkeypatch.setenv("PORTH_TENANTS_TABLE", TABLES["tenants"])
        monkeypatch.setenv("PORTH_ROLES_TABLE", TABLES["roles"])
        monkeypatch.setenv("PORTH_PERMISSIONS_TABLE", TABLES["permissions"])
        monkeypatch.setenv("PORTH_CLAIM_MAPPING_CONFIGS_TABLE", TABLES["claims"])
        monkeypatch.setenv("PRAWF_AUDIT_TABLE", AUDIT)
        monkeypatch.setenv("PORTH_STACK_NAME", "serverlessrepo-porth-components")
        monkeypatch.setenv("ADAPTER_VERSION", "test-build")

        def published():
            out = []
            while True:
                msgs = sqs.receive_message(QueueUrl=queue, MaxNumberOfMessages=10).get("Messages", [])
                if not msgs:
                    return out
                for m in msgs:
                    out.append(json.loads(m["Body"])["detail-type"])
                    sqs.delete_message(QueueUrl=queue, ReceiptHandle=m["ReceiptHandle"])

        yield {"published": published}


def call(verb, payload=None, run_id="run-seed-1", dry_run=False, entity="porth-tenant"):
    request = {"contract_version": "1.0.0", "verb": verb, "run": {"run_id": run_id, "dry_run": dry_run}}
    if entity:
        request["entity"] = entity
    if payload is not None:
        request["payload"] = payload
    response = handler.handler(copy.deepcopy(request), None)
    result = validate_contract_response(response)
    assert result.valid, [str(e) for e in result.errors]
    return response


def rows():
    """Every row in the slot's tables, as (table, partition key, sort key)."""
    out = set()
    for kind, name in TABLES.items():
        for item in boto3.resource("dynamodb").Table(name).scan()["Items"]:
            out.add((kind, item.get("PK") or item.get("pk"), item.get("SK") or item.get("sk")))
    return out


def repos():
    from porth_common.providers.aws.repositories.tenant_repo import TenantRepository
    from porth_common.providers.aws.repositories.role_repo import RoleRepository
    from porth_common.providers.aws.repositories.permission_repo import PermissionRepository
    res = boto3.resource("dynamodb")
    return (TenantRepository(TABLES["tenants"], res, environment=SLOT),
            RoleRepository(TABLES["roles"], res, environment=SLOT),
            PermissionRepository(TABLES["permissions"], res, environment=SLOT))


# ---------------------------------------------------------------- seed

def test_seed_writes_the_tenant_porth_0_3_1_writes_and_porth_reads_it_back(porth):
    response = call("seed", {"dataset": ems_test()})
    assert response["outcome"] == "ok", response
    (handle,) = response["results"]
    assert handle == {"alias": "ems-test", "type": "tenant", "entity": "porth-tenant", "id": "ems-test",
                      "outcome": "created", "labels": {"run_id": "run-seed-1"}}
    assert any("sha256:" in m for m in response["diagnostics"]["messages"]), "the digest is echoed"

    tenants, _, _ = repos()
    tenant = tenants.get_by_id("ems-test")
    assert (tenant.display_name, tenant.tenant_tier, tenant.status, tenant.org_id, tenant.org_name) == \
        ("EMS Test Tenant", "development", "active", ORG_ID, "EMS")
    assert tenant.created_by == "prawf:run-seed-1"
    listed, _ = tenants.list_all()
    assert "ems-test" in {t.tenant_id for t in listed}, "gsi2 lists it - GET /tenants/ will show it"


def test_porths_directory_scan_still_loads_and_sees_only_tenants(porth):
    """A row that matched the directory's filter and failed validation would empty it - every login
    in the slot would fail. The ledger lives in the same table; it must never match."""
    call("seed", {"dataset": ems_test()})
    tenants, _, _ = repos()
    loaded = tenants.list_all_with_environment()
    assert sorted(t.tenant_id for _, t in loaded) == ["ems-test", "platform"]
    assert {env for env, _ in loaded} == {SLOT}


def test_seed_provisions_the_tenant_admin_role_as_porth_0_3_1_did(porth):
    call("seed", {"dataset": ems_test()})
    _, roles, permissions = repos()
    (role,) = roles.list_roles("ems-test")
    assert (role.name, role.source_key, role.is_system) == ("tenant-admin", "tenant-admin", True)
    registered = {p.key for p in permissions.list_by_tenant("ems-test")}
    assert registered == {"tenant.roles.create", "tenant.roles.update", "tenant.roles.delete"}
    granted = set(roles.get_role_permissions("ems-test", role.id))
    assert granted == registered


#: The manifest's IdP block, as Porth's TenantIdpConfig carries it - synthetic values.
IDP = {"issuer": "https://idp.synthetic.test/", "jwks_uri": "https://idp.synthetic.test/.well-known/jwks.json",
       "client_id": "synthetic-tenant-client", "audience": "https://api.synthetic.test", "protocol": "oidc",
       "provider_org_id": "org_synthetic"}


def test_the_tenants_idp_config_is_seeded_with_it_and_porth_reads_it(porth):
    """Richard, 2026-10-25: the IdP config is part of the tenant - an attribute of its row."""
    response = call("seed", {"dataset": ems_test(idp_config_override=IDP)})
    assert response["outcome"] == "ok", response
    tenants, _, _ = repos()
    tenant = tenants.get_by_id("ems-test")
    assert tenant.idp_config_override.model_dump(exclude_none=True) == IDP
    row = boto3.resource("dynamodb").Table(TABLES["tenants"]).get_item(
        Key={"PK": f"ENV#{SLOT}#TENANT#ems-test", "SK": "METADATA"})["Item"]
    assert row["idp_config_override"] == IDP, "stored as a map, unset fields left out - as PATCH stores it"


def test_porths_tenant_directory_resolves_a_token_to_the_seeded_tenant(porth, monkeypatch):
    """What the IdP config is for: Porth's tenant directory - the lookup every sign-in makes - maps a
    token's (issuer, client_id, org) to its tenant. Loaded from the seeded table by Porth's own code."""
    import porth_common.config as config
    from porth_common.tenants import directory

    call("seed", {"dataset": ems_test(idp_config_override=IDP)})
    monkeypatch.setattr(config, "TABLE_PORTH_TENANTS", TABLES["tenants"], raising=False)
    directory.reset()
    try:
        found = directory.get(IDP["issuer"], IDP["client_id"], IDP["provider_org_id"])
    finally:
        directory.reset()
    assert found is not None and found.get("tenant_id") == "ems-test", found


def test_the_idp_config_publishes_the_update_porth_would(porth):
    call("seed", {"dataset": ems_test(idp_config_override=IDP)})
    published = porth["published"]()
    assert {"Tenant.created", "Tenant.updated", "tenant.updated"} <= set(published), published


def test_an_idp_config_porth_would_reject_is_refused_before_anything_is_written(porth):
    before = rows()
    response = call("seed", {"dataset": ems_test(idp_config_override={"issuer": "https://x/"})})
    assert (response["outcome"], response["reason_code"]) == ("refused", "dataset_conflict")
    assert "idp_config_override" in response["diagnostics"]["messages"][0]
    assert rows() == before


def test_seed_publishes_the_events_porth_would(porth):
    call("seed", {"dataset": ems_test()})
    published = porth["published"]()
    assert {"Tenant.created", "tenant.created"} <= set(published), published


def test_the_same_dataset_again_is_unchanged_and_writes_nothing(porth):
    call("seed", {"dataset": ems_test()})
    before = rows()
    response = call("seed", {"dataset": ems_test()}, run_id="run-seed-2")
    assert response["outcome"] == "ok"
    (handle,) = response["results"]
    assert handle["outcome"] == "unchanged"
    assert handle["labels"] == {"run_id": "run-seed-1"}, "labelled with the run that wrote it"
    assert rows() == before


def test_a_different_dataset_on_a_seeded_entity_is_refused(porth):
    call("seed", {"dataset": ems_test()})
    response = call("seed", {"dataset": ems_test(version="1.1.0")}, run_id="run-seed-2")
    assert (response["outcome"], response["reason_code"]) == ("refused", "dataset_conflict")


def test_an_existing_tenant_is_never_overwritten(porth):
    boto3.resource("dynamodb").Table(TABLES["tenants"]).put_item(Item={
        "PK": f"ENV#{SLOT}#TENANT#ems-test", "SK": "METADATA", "tenant_id": "ems-test", "org_id": ORG_ID,
        "display_name": "Someone else's", "tenant_tier": "sandbox", "status": "active",
        "created_at": "x", "updated_at": "x"})
    before = rows()
    response = call("seed", {"dataset": ems_test()})
    assert (response["outcome"], response["reason_code"]) == ("refused", "dataset_conflict")
    assert rows() == before
    tenants, _, _ = repos()
    assert tenants.get_by_id("ems-test").display_name == "Someone else's"


def test_a_missing_org_is_refused_not_created(porth):
    before = rows()
    response = call("seed", {"dataset": ems_test(org="nowhere")})
    assert (response["outcome"], response["reason_code"]) == ("refused", "dataset_conflict")
    assert rows() == before


def test_c14_a_dry_run_writes_nothing_and_says_what_it_would_do(porth):
    before = rows()
    response = call("seed", {"dataset": ems_test()}, dry_run=True)
    assert response["outcome"] == "ok"
    assert response["results"][0]["outcome"] == "created"
    assert rows() == before
    assert porth["published"]() == []


@pytest.mark.parametrize("dataset, outcome", [
    ({"id": "ems.ems-test-tenant", "version": "1.0.0", "digest": "sha256:" + "a" * 64}, ("unsupported", "not_implemented")),
    ({**ems_test(), "digest": "sha256:" + "0" * 64}, ("refused", "dataset_conflict")),
    (ems_test(tenant_tier="standard"), ("refused", "dataset_conflict")),
    (ems_test(provider_org_id="org_x"), ("refused", "dataset_conflict")),
])
def test_a_dataset_that_cannot_be_applied_writes_nothing(porth, dataset, outcome):
    before = rows()
    response = call("seed", {"dataset": dataset})
    assert (response["outcome"], response["reason_code"]) == outcome
    assert rows() == before


# ---------------------------------------------------------------- teardown

def test_c7_teardown_leaves_nothing_labelled_with_the_run(porth):
    before = rows()
    call("seed", {"dataset": ems_test()})
    porth["published"]()
    response = call("teardown", {"run_id": "run-seed-1"}, run_id="run-teardown-1")
    assert response["outcome"] == "ok"
    assert rows() == before, "back to exactly the slot as it was: platform tenant and org untouched"
    assert {"Tenant.deleted", "tenant.deleted"} <= set(porth["published"]())


def test_teardown_is_idempotent(porth):
    call("seed", {"dataset": ems_test()})
    call("teardown", {"run_id": "run-seed-1"}, run_id="run-teardown-1")
    again = call("teardown", {"run_id": "run-seed-1"}, run_id="run-teardown-2")
    assert again["outcome"] == "ok"
    assert any("nothing" in m for m in again["diagnostics"]["messages"])


def test_teardown_with_the_entity_omitted_reaches_porth_tenant(porth):
    before = rows()
    call("seed", {"dataset": ems_test()})
    call("teardown", {"run_id": "run-seed-1"}, run_id="run-teardown-1", entity=None)
    assert rows() == before


def test_after_teardown_the_same_dataset_seeds_again(porth):
    call("seed", {"dataset": ems_test()})
    call("teardown", {"run_id": "run-seed-1"}, run_id="run-teardown-1")
    response = call("seed", {"dataset": ems_test()}, run_id="run-seed-2")
    assert response["results"][0]["outcome"] == "created"


def test_a_seed_that_fails_part_way_is_failed_and_still_tears_down(porth, monkeypatch):
    """Porth's code raises after the tenant row is written (here: the role). The answer is `failed`,
    not a crash, and the ledger - written ahead of every write - still covers what landed."""
    before = rows()
    from porth_common.providers.aws.repositories import role_repo

    def boom(*args, **kwargs):
        raise RuntimeError("simulated failure after the tenant row")

    with monkeypatch.context() as m:
        m.setattr(role_repo.RoleRepository, "create_role", boom)
        response = call("seed", {"dataset": ems_test()})
    assert (response["outcome"], response["reason_code"]) == ("failed", "upstream_error")
    assert any(("TENANT#ems-test" in pk) for _, pk, _ in rows() - before), "the tenant row did land"
    call("teardown", {"run_id": "run-seed-1"}, run_id="run-teardown-1")
    assert rows() == before


def test_no_response_carries_a_credential(porth):
    responses = [call("seed", {"dataset": ems_test()}), call("teardown", {"run_id": "run-seed-1"}, run_id="t")]
    blob = json.dumps(responses)
    for secret in ("testing", os.environ["AWS_SECRET_ACCESS_KEY"]):
        assert f'"{secret}"' not in blob
