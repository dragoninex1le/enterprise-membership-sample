"""Offline behavioural tests for the QA seed Lambda.

No AWS: DynamoDB and SSM are in-memory fakes. These gate the deploy because every failure mode
this Lambda has is *silent* — records written at the wrong key still write successfully, and the
authorizer simply reports the tenant does not exist (PORTH-514).

The assertions pin the things that have already gone wrong somewhere in this system:

* **ADR-Z8** — the environment belongs in the *content* of partition keys only. A scoped sort key
  breaks every ``begins_with`` query; an unscoped ``PK`` is invisible to a pinned authorizer.
* **PORTH-502** — ``environment_type`` was renamed ``tenant_tier``.
* **PORTH-479** — a tenant without a claim-mapping config logs *"no claim mapping config for
  tenant=…; roles will be empty"* and its admin gets no menu. A seeded tenant missing one is a
  broken tenant that looks fine.
* **The Tier 2 reserved names** — ``frontend/tests/e2e/tier2/acceptance.spec.ts`` creates
  ``demo-tenant`` / ``Demo Corp`` itself and finds its row with
  ``getByRole('row').filter({hasText}).first()``. That is a substring match in DOM order, and the
  next action writes IdP config onto whatever row matched. A seeded near-miss silently clobbers
  the wrong tenant's config.
"""

import json
import os
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "seed"))

os.environ.setdefault("PORTH_ENV", "dev")
os.environ.setdefault("AWS_REGION", "us-east-1")

AUTH_BLOB = {
    "issuer": "https://example.eu.auth0.com/",
    "jwks_uri": "https://example.eu.auth0.com/.well-known/jwks.json",
    "interactive_client_id": "test-client-id",
    "audience": "https://porth-api.example.test",
}

TENANT = {
    "tenant_id": "acme",
    "display_name": "Acme Corp",
    "tenant_tier": "standard",
    "porth_org_id": "ems",
    "provider_org_id": "org_TESTTESTTESTTEST",
    "admin": {
        "email": "test-admin@acme.ems.test",
        "password_ssm": "/porth/testbed/tenants/acme/password",
    },
}


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeTable:
    def __init__(self, store, name):
        self.name = name
        self.store = store.setdefault(name, {})

    # The seeder checks for this before using the gsi1 query path.
    global_secondary_indexes = [{"IndexName": "gsi1"}]

    @staticmethod
    def _key(key):
        return tuple(key[k] for k in sorted(key))

    def get_item(self, Key):
        item = self.store.get(self._key(Key))
        return {"Item": item} if item else {}

    def put_item(self, Item):
        self.store[(Item.get("PK", Item.get("pk")), Item.get("SK", Item.get("sk")))] = dict(Item)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues):
        item = self.store.setdefault(self._key(Key), dict(Key))
        for fragment in UpdateExpression.replace("SET ", "").split(","):
            field, placeholder = (s.strip() for s in fragment.split("="))
            item[field] = ExpressionAttributeValues[placeholder]

    def query(self, KeyConditionExpression, **kwargs):
        items = [i for i in self.store.values() if _matches(i, KeyConditionExpression)]
        items.sort(
            key=lambda i: str(i.get("SK", i.get("sk", ""))),
            reverse=not kwargs.get("ScanIndexForward", True),
        )
        limit = kwargs.get("Limit")
        return {"Items": items[:limit] if limit else items}

    def scan(self, **kwargs):
        items = list(self.store.values())
        condition = kwargs.get("FilterExpression")
        if condition is not None:
            items = [i for i in items if _matches(i, condition)]
        return {"Items": items}


def _matches(item, condition) -> bool:
    """Evaluate a boto3 ``Key`` condition tree against a plain dict."""
    expr = condition.get_expression()
    if all(hasattr(v, "get_expression") for v in expr["values"]):  # AND / OR node
        return all(_matches(item, v) for v in expr["values"])

    operator = expr["operator"]
    actual = item.get(expr["values"][0].name)
    expected = expr["values"][1]
    if operator == "=":
        return actual == expected
    if operator == "begins_with":
        return isinstance(actual, str) and actual.startswith(expected)
    raise AssertionError(f"fake does not implement operator {operator!r}")


class FakeSSM:
    def __init__(self, blob, existing_params=()):
        self.blob = blob
        self.params = dict.fromkeys(existing_params, "unused")
        self.written = {}

    def get_parameter(self, Name, **kwargs):
        from botocore.exceptions import ClientError

        if Name == "/porth/auth" and self.blob is not None:
            return {"Parameter": {"Value": json.dumps(self.blob)}}
        if Name in self.params:
            # WithDecryption=False is the point — the seeder must never read a password value.
            assert kwargs.get("WithDecryption") is False, "password value must not be decrypted"
            return {"Parameter": {"Value": self.params[Name]}}
        raise ClientError({"Error": {"Code": "ParameterNotFound"}}, "GetParameter")

    def put_parameter(self, Name, Value, **kwargs):
        self.written[Name] = Value


@pytest.fixture
def env(monkeypatch):
    """A fresh in-memory account with /porth/auth and the tenant's password already present."""
    import boto3

    import handler

    store = {}
    ssm = FakeSSM(dict(AUTH_BLOB), existing_params=[TENANT["admin"]["password_ssm"]])
    monkeypatch.setattr(
        boto3, "resource",
        lambda *a, **k: types.SimpleNamespace(Table=lambda name: FakeTable(store, name)),
    )
    monkeypatch.setattr(boto3, "client", lambda *a, **k: ssm)

    def run(**payload):
        return json.loads(handler.handler(payload, None)["body"])

    return types.SimpleNamespace(store=store, ssm=ssm, run=run)


def _seed(env, **overrides):
    tenant = {**TENANT, **overrides}
    return env.run(env_scope="prod", tenants=[tenant])


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #
def test_creates_an_env_scoped_tenant(env):
    result = _seed(env)

    assert [r["status"] for r in result["results"]] == ["created"]
    assert result["results"][0]["warnings"] == []
    assert ("ENV#prod#TENANT#acme", "METADATA") in env.store["porth-tenants-dev"]


def test_environment_is_scoped_on_partition_keys_only(env):
    """ADR-Z8. A scoped sort key would make the environment an inner axis — wrong, and it
    silently breaks every begins_with query."""
    _seed(env)
    tenant = env.store["porth-tenants-dev"][("ENV#prod#TENANT#acme", "METADATA")]

    assert tenant["gsi1pk"].startswith("ENV#prod#ORG#")
    assert tenant["gsi1sk"] == "TENANT#acme"

    role = next(
        i for i in env.store["porth-roles-dev"].values() if i.get("name") == "tenant-admin"
    )
    assert role["pk"] == "ENV#prod#TENANT#acme"
    assert role["sk"].startswith("ROLE#") and "ENV#" not in role["sk"]


def test_writes_tenant_tier_not_environment_type(env):
    """PORTH-502 renamed the field."""
    tenant = _seed(env) and env.store["porth-tenants-dev"][("ENV#prod#TENANT#acme", "METADATA")]

    assert tenant["tenant_tier"] == "standard"
    assert "environment_type" not in tenant


def test_idp_config_comes_from_the_auth_blob_plus_provider_org(env):
    """PORTH-488 neutral OIDC, sourced from /porth/auth so no Auth0 credential is passed in.
    provider_org_id is what makes a tenant login resolve at all (PORTH-511)."""
    _seed(env)
    idp = env.store["porth-tenants-dev"][("ENV#prod#TENANT#acme", "METADATA")][
        "idp_config_override"
    ]

    assert idp["issuer"] == AUTH_BLOB["issuer"]
    assert idp["jwks_uri"] == AUTH_BLOB["jwks_uri"]
    assert idp["client_id"] == AUTH_BLOB["interactive_client_id"]
    assert idp["provider_org_id"] == TENANT["provider_org_id"]


def test_seeds_a_claim_mapping_config(env):
    """PORTH-479: without one the authorizer resolves no roles and the admin gets no menu."""
    from claim_mapping import COMPILED_HASH

    _seed(env)
    configs = env.store["porth-claim-mapping-configs-dev"]

    assert ("ENV#prod#TENANT#acme", "VERSION#000001") in configs
    assert configs[("ENV#prod#TENANT#acme", "VERSION#000001")]["compiled_hash"] == COMPILED_HASH


def test_tenant_admin_role_carries_source_key(env):
    """source_key is what the claim mapping resolves the IdP role claim against — without it
    the role exists but is never assigned to anyone."""
    _seed(env)
    role = next(
        i for i in env.store["porth-roles-dev"].values() if i.get("name") == "tenant-admin"
    )

    assert role["source_key"] == "tenant-admin"


def test_publishes_the_manifest_without_credentials(env):
    """The PORTH-494 config is generated from this, so it must carry ids and paths only."""
    result = _seed(env)
    manifest = json.loads(env.ssm.written["/porth/testbed/tenants"])

    assert manifest["env_scope"] == "prod"
    assert [t["tenant_id"] for t in manifest["tenants"]] == ["acme"]
    assert manifest["tenants"][0]["porth_org_uuid"] == result["results"][0]["porth_org_uuid"]
    assert "password" not in json.dumps(manifest).lower()


def test_is_idempotent(env):
    first = _seed(env)
    sizes = {table: len(items) for table, items in env.store.items()}

    second = _seed(env)

    assert second["results"][0]["status"] == "adopted"
    assert second["results"][0]["porth_org_uuid"] == first["results"][0]["porth_org_uuid"]
    assert second["results"][0]["role_id"] == first["results"][0]["role_id"]
    assert {table: len(items) for table, items in env.store.items()} == sizes


def test_many_tenants_share_one_org(env):
    """TenantsPage.loadAll() is 1 + N unpaginated requests, so few orgs is the cheap shape."""
    second = {**TENANT, "tenant_id": "globex", "display_name": "Globex"}
    result = env.run(env_scope="prod", tenants=[TENANT, second])

    org_uuids = {r["porth_org_uuid"] for r in result["results"]}
    assert len(org_uuids) == 1


# --------------------------------------------------------------------------- #
# Guards
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", "demo-tenant"),
        ("tenant_id", "demo-tenant-2"),       # substring — the row filter would still match
        ("display_name", "Demo Corp"),
        ("display_name", "ACME (demo corp)"),
        ("display_name", "DEMO CORP"),        # case-insensitive
        ("porth_org_id", "demo-tenant-org"),
    ],
)
def test_rejects_names_the_e2e_test_owns(env, field, value):
    result = _seed(env, **{field: value})

    assert result["error"] == "Manifest validation failed"
    assert any("e2e test owns" in d for d in result["details"])
    assert env.store.get("porth-tenants-dev", {}) == {}


def test_rejects_an_inline_password(env):
    """Passwords belong in SSM SecureString. A public repo's Actions log masks only the exact
    registered secret value — not one embedded in a JSON manifest."""
    result = _seed(env, admin={"email": "a@b.test", "password": "hunter2"})

    assert result["error"] == "Manifest validation failed"
    assert any("password_ssm" in d for d in result["details"])


def test_requires_a_password_path(env):
    result = _seed(env, admin={"email": "a@b.test"})

    assert any("password_ssm is required" in d for d in result["details"])


def test_rejects_a_malformed_tenant_id(env):
    result = _seed(env, tenant_id="Not_A_Valid_ID")

    assert any("lowercase alphanumeric" in d for d in result["details"])


def test_validates_the_whole_manifest_before_writing_anything(env):
    """A partial seed is worse than none — it leaves the testbed in an undefined state."""
    bad = {**TENANT, "tenant_id": "demo-tenant"}

    result = env.run(env_scope="prod", tenants=[TENANT, bad])

    assert result["error"] == "Manifest validation failed"
    assert env.store.get("porth-tenants-dev", {}) == {}


def test_skips_tenants_reserved_for_e2e(env):
    """Tier 2 creates its own tenant in beforeAll; seeding that slot makes the test fight us."""
    result = _seed(env, reserved_for_e2e=True)

    assert result["results"][0]["status"] == "skipped"
    assert result["results"][0]["reason"] == "reserved_for_e2e"
    assert env.store.get("porth-tenants-dev", {}) == {}


def test_warns_when_the_password_parameter_is_absent(env):
    """Not fatal — the Auth0 user is created out of band — but logins will fail without it."""
    result = _seed(env, admin={**TENANT["admin"], "password_ssm": "/porth/testbed/tenants/nope"})

    assert any("does not exist" in w for w in result["results"][0]["warnings"])


def test_warns_when_provider_org_id_is_missing(env):
    """PORTH-511 denies a non-platform-admin token with no org_id, so the tenant would exist
    but nobody could log into it."""
    result = _seed(env, provider_org_id="")

    assert any("PORTH-511" in w for w in result["results"][0]["warnings"])


def test_requires_an_explicit_env_scope(env, monkeypatch):
    monkeypatch.delenv("PORTH_ENV_SCOPE", raising=False)

    assert env.run(tenants=[TENANT])["error"].startswith("env_scope")


def test_rejects_an_empty_manifest(env):
    assert "non-empty" in env.run(env_scope="prod", tenants=[])["error"]


def test_fails_when_the_auth_blob_is_absent(env):
    """Seeding without an IdP config would create a tenant nobody can ever log in to, so this
    is fatal here — unlike the platform bootstrap, where the tenant is still worth creating."""
    env.ssm.blob = None

    assert "/porth/auth" in env.run(env_scope="prod", tenants=[TENANT])["error"]


def test_dry_run_writes_nothing(env):
    result = env.run(env_scope="prod", dry_run=True, tenants=[TENANT])

    assert result["dry_run"] is True
    assert all(items == {} for items in env.store.values())
    assert env.ssm.written == {}
