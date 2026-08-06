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

AUTH0_IDP = {
    "issuer": "https://example.eu.auth0.com/",
    "jwks_uri": "https://example.eu.auth0.com/.well-known/jwks.json",
    "client_id": "test-client-id",
    "audience": "https://porth-api.example.test",
    "protocol": "auth0",
}

# A second provider, to prove a tenant is not tied to the platform's IdP. Note the issuer has
# NO trailing slash — Keycloak differs from Auth0 here, and `iss` must match byte for byte.
KEYCLOAK_IDP = {
    "issuer": "https://kc.example.test/realms/porth",
    "jwks_uri": "https://kc.example.test/realms/porth/protocol/openid-connect/certs",
    "client_id": "porth-kc",
    "audience": "porth-api",
    "protocol": "oidc",
}

PLATFORM = {
    "idp": dict(AUTH0_IDP),
    "admin": {
        "email": "platform-admin@ems.test",
        "password_secret": "porth/testbed/platform/password",
    },
}

TENANT = {
    "tenant_id": "acme",
    "display_name": "Acme Corp",
    "tenant_tier": "sandbox",
    "porth_org_id": "ems",
    "provider_org_id": "org_TESTTESTTESTTEST",
    "idp": dict(AUTH0_IDP),
    "admin": {
        "email": "test-admin@acme.ems.test",
        "password_secret": "porth/testbed/tenants/acme/password",
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
    def __init__(self, manifest=None):
        self.manifest = manifest
        self.written = {}

    def get_parameter(self, Name, **kwargs):
        from botocore.exceptions import ClientError

        if Name == "/porth/config/testbed" and self.manifest is not None:
            # The parameter may be a SecureString; without WithDecryption the caller would
            # get KMS ciphertext back and fail JSON parsing on something inscrutable.
            assert kwargs.get("WithDecryption") is True, "manifest must be read decrypted"
            return {"Parameter": {"Value": self.manifest}}
        raise ClientError({"Error": {"Code": "ParameterNotFound"}}, "GetParameter")

    def put_parameter(self, Name, Value, **kwargs):
        self.written[Name] = Value


class FakeSecrets:
    """DescribeSecret only. GetSecretValue is deliberately absent — if the seeder ever tries
    to read a password value, these tests fail with AttributeError rather than passing."""

    def __init__(self, existing=()):
        self.existing = set(existing)

    def describe_secret(self, SecretId):
        from botocore.exceptions import ClientError

        if SecretId in self.existing:
            return {"Name": SecretId, "ARN": f"arn:aws:secretsmanager:::secret:{SecretId}-AbCdEf"}
        raise ClientError({"Error": {"Code": "ResourceNotFoundException"}}, "DescribeSecret")


@pytest.fixture
def env(monkeypatch):
    """A fresh in-memory account with /porth/auth and the tenant's password already present."""
    import boto3

    import handler

    store = {}
    ssm = FakeSSM(manifest=json.dumps({"platform": PLATFORM, "tenants": [TENANT]}))
    secrets = FakeSecrets(existing=[
        TENANT["admin"]["password_secret"], PLATFORM["admin"]["password_secret"],
    ])
    clients = {"ssm": ssm, "secretsmanager": secrets}

    monkeypatch.setattr(
        boto3, "resource",
        lambda *a, **k: types.SimpleNamespace(Table=lambda name: FakeTable(store, name)),
    )
    monkeypatch.setattr(boto3, "client", lambda service, **k: clients[service])

    def run(**payload):
        return json.loads(handler.handler(payload, None)["body"])

    return types.SimpleNamespace(store=store, ssm=ssm, secrets=secrets, run=run)


def _seed(env, **overrides):
    tenant = {**TENANT, **overrides}
    return env.run(env_scope="prod", tenants=[tenant])


# --------------------------------------------------------------------------- #
# The shipped example
# --------------------------------------------------------------------------- #
def test_the_example_manifest_validates():
    """An example that does not validate is worse than no example — it sends an operator
    debugging their own copy of a shape that was never right."""
    import handler

    raw = json.loads(
        (Path(__file__).resolve().parents[1] / "testbed-manifest.example.json").read_text()
    )

    def strip(node):
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k != "_comment"}
        if isinstance(node, list):
            return [strip(v) for v in node]
        return node

    manifest = strip(raw)
    problems = [f"platform: {e}" for e in handler._validate_platform(manifest["platform"])]
    for i, t in enumerate(manifest["tenants"]):
        problems += [f"tenants[{i}] ({t.get('tenant_id')}): {e}"
                     for e in handler._validate_tenant(t)]

    assert problems == []

    # It must also demonstrate the things it claims to: more than one provider, and the
    # reserved slot using the name the guard would otherwise reject.
    protocols = {(t.get("idp") or {}).get("protocol") for t in manifest["tenants"]}
    assert {"auth0", "oidc"} <= protocols
    assert any(t.get("reserved_for_e2e") and t["tenant_id"] == "demo-tenant"
               for t in manifest["tenants"])


# --------------------------------------------------------------------------- #
# The manifest lives in SSM, not in the caller
# --------------------------------------------------------------------------- #
def test_reads_the_manifest_from_ssm_when_the_caller_supplies_none(env):
    """The invoking workflow passes only env_scope. The testbed's configuration lives in the
    account it configures, so it never transits a public repo's CI."""
    result = env.run(env_scope="prod")

    assert [r["tenant_id"] for r in result["results"]] == ["acme"]
    assert ("ENV#prod#TENANT#acme", "METADATA") in env.store["porth-tenants-dev"]


def test_accepts_a_bare_array_manifest(env):
    """Tolerate `[...]` as well as `{"tenants": [...]}` — an operator hand-writing the
    parameter should not have to guess."""
    env.ssm.manifest = json.dumps([TENANT])

    assert env.run(env_scope="prod")["results"][0]["status"] == "created"


def test_an_inline_manifest_overrides_ssm(env):
    """Used by these tests and for a one-off dry run against a candidate manifest."""
    override = {**TENANT, "tenant_id": "globex", "display_name": "Globex"}

    result = env.run(env_scope="prod", tenants=[override])

    assert [r["tenant_id"] for r in result["results"]] == ["globex"]


def test_names_the_ssm_parameter_when_the_manifest_is_absent(env):
    """The operator has to know *where* to put it, and it is not in this repo."""
    env.ssm.manifest = None

    error = env.run(env_scope="prod")["error"]

    assert "/porth/config/testbed" in error
    assert "put-parameter" in error


def test_reports_a_malformed_manifest_clearly(env):
    env.ssm.manifest = "{not json"

    assert "not valid JSON" in env.run(env_scope="prod")["error"]


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

    assert tenant["tenant_tier"] == "sandbox"
    assert "environment_type" not in tenant


def test_written_tier_is_one_the_porth_model_accepts(env):
    """The rename this file already covers changed the allowed VALUES too.

    Asserting only that the field is *named* `tenant_tier` is what let the invalid default
    "standard" survive PORTH-502. DynamoDB accepted it, the seeder reported `created`, and
    the row then 400'd on every read because the API could not build a Tenant from it —
    invisible in the admin UI, no error anywhere in the chain. Pin the value, not the key.
    """
    import handler

    _seed(env)
    tenant = env.store["porth-tenants-dev"][("ENV#prod#TENANT#acme", "METADATA")]

    assert tenant["tenant_tier"] in handler.TENANT_TIERS


def test_tier_defaults_to_a_valid_value_when_the_manifest_omits_it(env):
    """The live manifest sets no tier, so the default is the path that actually runs."""
    import handler

    _seed(env, tenant_tier=None)
    tenant = env.store["porth-tenants-dev"][("ENV#prod#TENANT#acme", "METADATA")]

    assert tenant["tenant_tier"] == handler.DEFAULT_TENANT_TIER
    assert handler.DEFAULT_TENANT_TIER in handler.TENANT_TIERS


def test_rejects_a_tier_outside_the_set_the_model_allows(env):
    """Fail in the dry run, not days later as a row that will not render."""
    result = _seed(env, tenant_tier="enterprise")

    assert result["error"] == "Manifest validation failed"
    assert any("tenant_tier" in d for d in result["details"])
    assert env.store.get("porth-tenants-dev", {}) == {}


def test_idp_config_is_written_verbatim_from_the_tenant(env):
    """Each tenant carries its own block. provider_org_id sits outside it — a Porth-level
    tenant fact (PORTH-511) that a non-Auth0 tenant has no equivalent for."""
    _seed(env)
    idp = env.store["porth-tenants-dev"][("ENV#prod#TENANT#acme", "METADATA")][
        "idp_config_override"
    ]

    for key, value in AUTH0_IDP.items():
        assert idp[key] == value
    assert idp["provider_org_id"] == TENANT["provider_org_id"]


def test_a_tenant_can_run_on_a_different_provider(env):
    """The point of PORTH-488's neutral issuer/jwks_uri pair — the testbed must be able to
    exercise more than one IdP at a time, not just N tenants on one Auth0 app."""
    kc = {**TENANT, "tenant_id": "initech", "display_name": "Initech",
          "idp": dict(KEYCLOAK_IDP)}
    kc.pop("provider_org_id")
    env.secrets.existing.add(kc["admin"]["password_secret"])

    env.run(env_scope="prod", tenants=[kc])
    idp = env.store["porth-tenants-dev"][("ENV#prod#TENANT#initech", "METADATA")][
        "idp_config_override"
    ]

    assert idp["issuer"] == KEYCLOAK_IDP["issuer"]
    assert not idp["issuer"].endswith("/"), "Keycloak issuers have no trailing slash"
    assert idp["protocol"] == "oidc"
    # No Auth0 leakage from the platform block.
    assert "end_session_endpoint" not in idp
    assert "provider_org_id" not in idp


def test_rejects_an_idp_missing_the_neutral_oidc_pair(env):
    """PORTH-488 requires both halves; one without the other cannot validate a token."""
    result = _seed(env, idp={"client_id": "x", "audience": "y"})

    details = " ".join(result["details"])
    assert "idp.issuer is required" in details
    assert "idp.jwks_uri is required" in details


def test_rejects_a_non_absolute_issuer(env):
    result = _seed(env, idp={**AUTH0_IDP, "issuer": "example.eu.auth0.com"})

    assert any("must be an absolute URL" in d for d in result["details"])


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


def test_publishes_the_resolved_set_with_identities_but_no_credentials(env):
    """The PORTH-494 config and the e2e suite are generated from this, so it carries every
    identity and where to fetch its credential — but never a credential value."""
    result = env.run(env_scope="prod")
    published = json.loads(env.ssm.written["/porth/testbed/tenants"])

    assert published["env_scope"] == "prod"
    assert [t["tenant_id"] for t in published["tenants"]] == ["acme"]
    assert published["tenants"][0]["porth_org_uuid"] == result["results"][0]["porth_org_uuid"]
    assert published["tenants"][0]["admin"]["email"] == TENANT["admin"]["email"]
    assert published["tenants"][0]["admin"]["password_secret"] == TENANT["admin"]["password_secret"]

    # The platform admin resolves from the same document, so nothing needs a GitHub secret.
    assert published["platform"]["admin"]["email"] == PLATFORM["admin"]["email"]
    assert published["platform"]["tenant_id"] == "platform"


def test_the_platform_tenant_is_declared_but_never_created(env):
    """Creating it is PORTH-536's job — it must exist before any login, including the
    install's own smoke test, so it is install-time rather than testbed-time."""
    result = env.run(env_scope="prod")

    assert result["platform_warnings"] == []
    assert ("ENV#prod#TENANT#platform", "METADATA") not in env.store["porth-tenants-dev"]
    assert [r["tenant_id"] for r in result["results"]] == ["acme"]


def test_warns_when_the_platform_secret_is_missing(env):
    env.secrets.existing.discard(PLATFORM["admin"]["password_secret"])

    assert any("does not exist" in w for w in env.run(env_scope="prod")["platform_warnings"])


def test_rejects_a_platform_block_without_an_idp(env):
    env.ssm.manifest = json.dumps(
        {"platform": {"admin": PLATFORM["admin"]}, "tenants": [TENANT]}
    )

    result = env.run(env_scope="prod")

    assert any(d.startswith("platform: idp") for d in result["details"])


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
    assert any("password_secret" in d for d in result["details"])


def test_requires_a_password_path(env):
    result = _seed(env, admin={"email": "a@b.test"})

    assert any("password_secret is required" in d for d in result["details"])


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
    result = _seed(env, admin={**TENANT["admin"], "password_secret": "porth/testbed/nope"})

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


def test_a_reserved_entry_may_use_the_name_the_e2e_test_owns(env):
    """The whole point of the flag. The name guard stops a *seeded* near-miss clobbering that
    tenant's config — which cannot happen when nothing is seeded. Applying it here would make
    the flag unusable for the only name it is ever needed for."""
    reserved = {"tenant_id": "demo-tenant", "display_name": "Demo Corp",
                "reserved_for_e2e": True}

    result = env.run(env_scope="prod", tenants=[TENANT, reserved])

    assert [r["status"] for r in result["results"]] == ["created", "skipped"]
    assert ("ENV#prod#TENANT#demo-tenant", "METADATA") not in env.store["porth-tenants-dev"]


def test_a_reserved_entry_needs_no_idp_or_admin(env):
    """Nothing is written for it, so requiring an identity would be noise."""
    reserved = {"tenant_id": "spare-slot", "reserved_for_e2e": True}

    result = env.run(env_scope="prod", tenants=[TENANT, reserved])

    assert result["results"][1]["status"] == "skipped"


def test_dry_run_writes_nothing(env):
    result = env.run(env_scope="prod", dry_run=True, tenants=[TENANT])

    assert result["dry_run"] is True
    assert all(items == {} for items in env.store.values())
    assert env.ssm.written == {}
