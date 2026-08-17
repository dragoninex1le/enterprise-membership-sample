"""QA seed Lambda — provisions synthetic test tenants on demand (PORTH-530).

Companion to the QA cleanup Lambda: cleanup empties the tables, this refills them with the
deterministic test context the Tier 2 e2e suite and the PORTH-494 security lab both need.

POST /qa/seed with a JSON body (the manifest):

    {
      "env_scope": "prod",                      // optional; default PORTH_ENV_SCOPE
      "dry_run": false,                         // optional; validate + plan only
      "tenants": [
        {
          "tenant_id": "acme",
          "display_name": "Acme Corp",
          "tenant_tier": "sandbox",             // optional; one of TENANT_TIERS
          "porth_org_id": "ems",                // org slug — find-or-create, resolved to a UUID
          "provider_org_id": "org_XXXX",        // Auth0 Organization id (required for tenant login)
          "reserved_for_e2e": false,            // true => skipped, the slot is left for the e2e test
          "idp": { "issuer": "...", "jwks_uri": "...", "client_id": "...",
                   "audience": "...", "protocol": "auth0" },
          "admin": { "email": "...", "password_secret": "porth/testbed/tenants/acme/password" }
        }
      ]
    }

Returns a per-tenant summary: created | adopted | skipped, plus any warnings.

**Why it writes DynamoDB directly** rather than calling the Porth API: same reason
`reset-env.yml` bootstraps the platform tenant that way — the API path needs EventBridge
PutEvents (which this role deliberately lacks) and an auth token. Writing the records directly
keeps the Lambda dependency-free and means no Porth API credential has to exist anywhere.

**Why it does not generate passwords:** the matching user must exist in Auth0, which needs the
Management API. Passwords are therefore created out-of-band alongside the Auth0 user and stored
at `admin.password_secret`. This Lambda only calls DescribeSecret — metadata, structurally
incapable of returning the value. Nothing secret is returned or logged.

Safety:
- Only deployed to dev/staging (SAM template restricts Environment).
- Every partition key is written env-scoped as `ENV#{env_scope}#…` (ADR-Z8) so records land where
  an authorizer pinned to that environment will actually find them.
- Idempotent: create-or-adopt. It never deletes or renames anything.
- Refuses to touch the `demo-tenant` / `Demo Corp` names the Tier 2 e2e test owns, and rejects any
  name that *contains* them (its row lookup is a substring match — a near-miss would make the test
  rewrite the wrong tenant's IdP config).
- AWS_IAM auth on the API Gateway route.
"""

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

import claim_mapping

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Names owned by the Tier 2 e2e test (frontend/tests/e2e/tier2/acceptance.spec.ts). It creates
# these itself and tolerates a 409; its row lookup is `filter({hasText}).first()` — a substring
# match in DOM order — and the next action writes IdP config onto whatever row matched. So a
# seeded name merely *containing* one of these can make the test clobber the wrong tenant.
RESERVED_NAMES = ("demo-tenant", "demo corp")

# INPUT: the tenant manifest, authored by the operator. It lives in SSM rather than as a
# GitHub variable so the testbed's configuration lives in the account it configures — this
# repo is public, and config there is neither versioned, audited, nor reliably masked in
# logs. The invoking workflow passes only `env_scope`; the manifest never transits CI.
TESTBED_CONFIG_PARAM = "/porth/config/testbed"

# OUTPUT: the resolved set, with the org/role UUIDs Porth assigned. The PORTH-494 config is
# generated from this. Ids and SSM paths only — never a credential.
TESTBED_MANIFEST_PARAM = "/porth/testbed/tenants"

_TENANT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")

# Must mirror the pattern on porth_common.models.tenant.Tenant.tenant_tier. DynamoDB
# validates nothing, so a tier outside this set writes cleanly and then fails on every
# READ — the API cannot build a Tenant from the row and answers 400 on
# GET /tenants/organization/{id}. The seeder reports `created`, and the tenant is simply
# invisible in the admin UI with no error anywhere in the chain.
#
# PORTH-502 renamed environment_type -> tenant_tier and changed the allowed values with
# it. The old default "standard" was carried through unchanged, so every tenant this
# seeder has ever written was unreadable. Validated here as well as defaulted, so a bad
# value in the manifest fails the dry run rather than surfacing days later as a missing
# row.
TENANT_TIERS = ("production", "staging", "development", "sandbox")
DEFAULT_TENANT_TIER = "sandbox"


def handler(event, context):
    """Lambda entry point — API Gateway proxy, or a direct invoke with the same shape."""
    try:
        raw = event.get("body")
        body = json.loads(raw) if isinstance(raw, str) else (raw or event)
        if not isinstance(body, dict):
            raise ValueError("body is not an object")
    except (json.JSONDecodeError, TypeError, ValueError):
        return _response(400, {"error": "Invalid JSON body"})

    porth_env = os.environ.get("PORTH_ENV")
    if not porth_env:
        return _response(500, {"error": "Server misconfiguration: PORTH_ENV is not set"})

    # The ADR-Z8 data axis. Distinct from PORTH_ENV, which only suffixes table names — conflating
    # the two writes records the authorizer will never look for.
    env_scope = (body.get("env_scope") or os.environ.get("PORTH_ENV_SCOPE") or "").strip()
    if not env_scope:
        return _response(400, {"error": "env_scope is required (or set PORTH_ENV_SCOPE)"})

    dry_run = bool(body.get("dry_run"))

    region = os.environ.get("AWS_REGION", "us-east-1")
    dynamodb = boto3.resource("dynamodb", region_name=region)
    ssm = boto3.client("ssm", region_name=region)
    secrets = boto3.client("secretsmanager", region_name=region)

    # The manifest normally comes from SSM, so the caller passes nothing but env_scope and no
    # testbed configuration transits CI. An inline manifest overrides it — used by the tests
    # and for a one-off dry run against a candidate document.
    if body.get("tenants") is not None or body.get("platform") is not None:
        manifest = {"platform": body.get("platform"), "tenants": body.get("tenants")}
    else:
        try:
            manifest = _load_manifest(ssm)
        except ClientError as e:
            if e.response["Error"]["Code"] in ("ParameterNotFound", "AccessDeniedException"):
                return _response(400, {
                    "error": f"{TESTBED_CONFIG_PARAM} is absent — the tenant manifest lives "
                             f"there, not in the workflow. Create it with: aws ssm "
                             f"put-parameter --name {TESTBED_CONFIG_PARAM} --type SecureString "
                             f"--value file://manifest.json"
                })
            raise
        except (json.JSONDecodeError, TypeError) as e:
            return _response(400, {"error": f"{TESTBED_CONFIG_PARAM} is not valid JSON: {e}"})

    tenants = manifest.get("tenants")
    platform = manifest.get("platform")

    if not isinstance(tenants, list) or not tenants:
        return _response(400, {"error": "tenants must be a non-empty array"})

    # --- Validate the whole manifest before writing anything ------------------
    errors = []
    if platform is not None:
        errors.extend(f"platform: {e}" for e in _validate_platform(platform))
    for i, t in enumerate(tenants):
        errors.extend(f"tenants[{i}]: {e}" for e in _validate_tenant(t))
    if errors:
        return _response(400, {"error": "Manifest validation failed", "details": errors})

    tables = {
        "tenants": dynamodb.Table(f"porth-tenants-{porth_env}"),
        "roles": dynamodb.Table(f"porth-roles-{porth_env}"),
        "claims": dynamodb.Table(f"porth-claim-mapping-configs-{porth_env}"),
    }

    logger.info(
        "QA seed starting: env=%s env_scope=%s tenants=%d dry_run=%s",
        porth_env, env_scope, len(tenants), dry_run,
    )

    results = []
    for t in tenants:
        try:
            results.append(_seed_tenant(t, tables, secrets, env_scope, dry_run))
        except ClientError as e:
            code = e.response["Error"]["Code"]
            logger.error("seed failed for %s: %s", t.get("tenant_id"), code)
            results.append({
                "tenant_id": t.get("tenant_id"), "status": "error", "error": code,
            })

    # The platform tenant is NOT created here — PORTH-536 owns that, and duplicating it is
    # how the ADR-Z8 scoping bug spread in the first place. The block is validated and
    # published so every testbed identity resolves from one document.
    platform_warnings = []
    if platform:
        platform_warnings = _check_secret(secrets, platform["admin"]["password_secret"])

    seeded = [r for r in results if r["status"] in ("created", "adopted")]
    if seeded and not dry_run:
        _write_manifest(ssm, env_scope, seeded, tenants, platform)

    logger.info(
        "QA seed complete: created=%d adopted=%d skipped=%d error=%d",
        *[sum(1 for r in results if r["status"] == s)
          for s in ("created", "adopted", "skipped", "error")],
    )

    status = 200 if not any(r["status"] == "error" for r in results) else 207
    return _response(status, {
        "env_scope": env_scope,
        "dry_run": dry_run,
        "platform_warnings": platform_warnings,
        "results": results,
    })


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def _validate_platform(p) -> list:
    """The platform block declares the platform-admin identity and the platform IdP config.

    It is deliberately NOT seeded here: creating the platform tenant is PORTH-536's job, and
    it must exist before any login — including the install's own smoke test — so it is
    install-time, not testbed-time. Declaring it here gives every testbed identity one home.
    """
    if not isinstance(p, dict):
        return ["must be an object"]
    return _validate_admin(p.get("admin"), "admin") + _validate_idp(p.get("idp"), "idp")


def _validate_admin(admin, where: str) -> list:
    """Shared by the platform block and every tenant — one definition of 'an identity'."""
    if not isinstance(admin, dict) or not admin.get("email"):
        return [f"{where}.email is required"]
    if admin.get("password"):
        return [f"{where}.password must not be inline — use password_secret"]
    if not admin.get("password_secret"):
        return [f"{where}.password_secret is required (a Secrets Manager name or ARN, never a value)"]
    return []


def _validate_idp(idp, where: str) -> list:
    """PORTH-488: tenants resolve on a NEUTRAL OIDC pair, so both halves are mandatory.

    `issuer` must byte-match the `iss` claim in issued tokens. Providers differ on the
    trailing slash — Auth0 issues `https://host/`, Keycloak `https://host/realms/name` —
    and a mismatch surfaces as an opaque validation rejection, so it is worth being strict
    here rather than at 3am.
    """
    if not isinstance(idp, dict):
        return [f"{where} must be an object"]

    problems = [f"{where}.{k} is required" for k in ("issuer", "jwks_uri") if not idp.get(k)]
    issuer = idp.get("issuer")
    if isinstance(issuer, str) and issuer and not issuer.startswith(("http://", "https://")):
        problems.append(f"{where}.issuer '{issuer}' must be an absolute URL")
    return problems


def _validate_tenant(t) -> list:
    """Return a list of problems with one manifest entry (empty == valid)."""
    if not isinstance(t, dict):
        return ["must be an object"]

    tid = t.get("tenant_id")
    if not tid or not isinstance(tid, str):
        return ["tenant_id is required"]

    problems = []
    if not _TENANT_ID_RE.match(tid):
        problems.append(f"tenant_id '{tid}' must be lowercase alphanumeric/hyphen, 2-63 chars")

    # A reserved entry documents a slot the e2e suite owns; nothing is written for it. The
    # name guard below exists to stop a *seeded* near-miss clobbering that tenant's config,
    # which cannot happen when nothing is seeded — and applying it here would make the flag
    # unusable for the only name it is ever needed for.
    if t.get("reserved_for_e2e"):
        return problems

    for field in ("tenant_id", "display_name", "porth_org_id"):
        val = t.get(field)
        if isinstance(val, str):
            lowered = val.lower()
            for reserved in RESERVED_NAMES:
                if reserved in lowered:
                    problems.append(
                        f"{field} '{val}' contains '{reserved}', which the Tier 2 e2e test owns — "
                        f"its row lookup is a substring match and would target the wrong tenant"
                    )

    tier = t.get("tenant_tier")
    if tier is not None and tier not in TENANT_TIERS:
        problems.append(
            f"tenant_tier '{tier}' is not one of {', '.join(TENANT_TIERS)} — the row would "
            f"write cleanly and then 400 on every read"
        )

    problems.extend(_validate_admin(t.get("admin"), "admin"))
    problems.extend(_validate_idp(t.get("idp"), "idp"))
    return problems


# --------------------------------------------------------------------------- #
# Seeding
# --------------------------------------------------------------------------- #
def _seed_tenant(t, tables, secrets, env_scope, dry_run) -> dict:
    tid = t["tenant_id"]

    if t.get("reserved_for_e2e"):
        logger.info("skipping %s — reserved_for_e2e", tid)
        return {"tenant_id": tid, "status": "skipped", "reason": "reserved_for_e2e"}

    admin = t["admin"]
    warnings = _check_secret(secrets, admin["password_secret"])
    if not t.get("provider_org_id"):
        warnings.append(
            "no provider_org_id — PORTH-511 denies a non-platform-admin token without org_id, "
            "so tenant logins will not work until the provider's organization id is supplied"
        )

    if dry_run:
        # "planned", not "adopted" — nothing was written, and a dry run that reports the
        # same word as a real one is a dry run nobody can read.
        return {"tenant_id": tid, "status": "planned", "dry_run": True, "warnings": warnings}

    now = _utc_now()
    tenants_tbl = tables["tenants"]

    org_uuid, org_created = _find_or_create_org(
        tenants_tbl, t.get("porth_org_id") or tid, env_scope, now
    )

    tenant_pk = _env_key(env_scope, f"TENANT#{tid}")
    existing = tenants_tbl.get_item(Key={"PK": tenant_pk, "SK": "METADATA"}).get("Item")

    # The tenant's own IdP config, verbatim from the manifest. Written per tenant rather than
    # inherited from /porth/auth so the testbed can run tenants on different providers — which
    # is the point of PORTH-488's neutral issuer/jwks_uri pair. `provider_org_id` sits outside
    # the block because it is a Porth-level tenant fact; a Keycloak tenant has no equivalent.
    # `_`-prefixed keys are the manifest's comment convention (JSON has none) — strip them so
    # they never land in an auth config record.
    idp_config = {k: v for k, v in t["idp"].items() if not k.startswith("_")}
    if t.get("provider_org_id"):
        idp_config["provider_org_id"] = t["provider_org_id"]

    item = {
        "PK": tenant_pk,
        "SK": "METADATA",
        "gsi1pk": _env_key(env_scope, f"ORG#{org_uuid}"),
        "gsi1sk": f"TENANT#{tid}",
        "tenant_id": tid,
        "org_id": org_uuid,
        "org_name": t.get("porth_org_id") or tid,
        "display_name": t.get("display_name") or tid,
        # PORTH-502 renamed environment_type -> tenant_tier. The default must be a member
        # of TENANT_TIERS — see the note there; an invalid tier is write-valid, read-fatal.
        "tenant_tier": t.get("tenant_tier") or DEFAULT_TENANT_TIER,
        "status": "active",
        "idp_config_override": idp_config,
        "admin_email": admin["email"],
        "admin_password_secret": admin["password_secret"],
        "updated_at": now,
        "created_at": (existing or {}).get("created_at", now),
    }
    tenants_tbl.put_item(Item=item)

    role_id = _ensure_tenant_admin_role(tables["roles"], tid, env_scope, now)
    _ensure_claim_mapping(tables["claims"], tid, env_scope, now)

    status = "adopted" if existing else "created"
    logger.info(
        "%s tenant %s (org=%s role=%s)%s",
        status, tid, org_uuid, role_id, " [org created]" if org_created else "",
    )
    return {
        "tenant_id": tid,
        "status": status,
        "porth_org_uuid": org_uuid,
        "role_id": role_id,
        "warnings": warnings,
    }


def _find_or_create_org(tbl, slug, env_scope, now):
    """Resolve a Porth org by slug to its UUID, creating it if absent. (org_id is a UUID Porth
    assigns — the manifest supplies a human-readable slug, not the id.)"""
    resp = tbl.query(
        IndexName="gsi1",
        KeyConditionExpression=Key("gsi1pk").eq(_env_key(env_scope, f"ORG_SLUG#{slug}")),
        Limit=1,
    ) if _has_gsi(tbl) else {"Items": []}

    for it in resp.get("Items", []):
        if it.get("slug") == slug:
            return it["id"], False

    # Fall back to a direct lookup so a missing/renamed GSI doesn't cause duplicate orgs.
    scan = tbl.scan(
        FilterExpression=Key("SK").eq("METADATA"),
        ProjectionExpression="PK, id, slug",
    )
    for it in scan.get("Items", []):
        if it.get("slug") == slug and str(it.get("PK", "")).startswith(
            _env_key(env_scope, "ORG#")
        ):
            return it["id"], False

    org_uuid = str(uuid.uuid4())
    tbl.put_item(Item={
        "PK": _env_key(env_scope, f"ORG#{org_uuid}"),
        "SK": "METADATA",
        "gsi1pk": _env_key(env_scope, f"ORG_SLUG#{slug}"),
        "gsi1sk": "METADATA",
        "id": org_uuid,
        "name": slug,
        "slug": slug,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    })
    return org_uuid, True


def _ensure_tenant_admin_role(roles_tbl, tid, env_scope, now) -> str:
    """Create-or-adopt the tenant-admin role. `source_key` is what the claim mapping resolves the
    IdP's role claim against — without it the role exists but never gets assigned."""
    pk = _env_key(env_scope, f"TENANT#{tid}")
    resp = roles_tbl.query(
        KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with("ROLE#")
    )
    for item in resp.get("Items", []):
        if item.get("name") == "tenant-admin":
            role_id = item["id"]
            if item.get("source_key") != "tenant-admin":
                roles_tbl.update_item(
                    Key={"pk": pk, "sk": f"ROLE#{role_id}"},
                    UpdateExpression="SET source_key = :sk, updated_at = :ua",
                    ExpressionAttributeValues={":sk": "tenant-admin", ":ua": now},
                )
            return role_id

    role_id = str(uuid.uuid4())
    roles_tbl.put_item(Item={
        "pk": pk,
        "sk": f"ROLE#{role_id}",
        "id": role_id,
        "tenant_id": tid,
        "name": "tenant-admin",
        "is_system": True,
        "source_key": "tenant-admin",
        "description": "Tenant administrator (seeded by qa-tools)",
        "created_at": now,
        "updated_at": now,
    })
    return role_id


def _ensure_claim_mapping(claims_tbl, tid, env_scope, now) -> None:
    """Write the default claim-mapping config if this tenant has none at the current hash."""
    pk = _env_key(env_scope, f"TENANT#{tid}")
    existing = claims_tbl.query(
        KeyConditionExpression=Key("PK").eq(pk), ScanIndexForward=False, Limit=1
    )
    items = existing.get("Items", [])
    # PORTH-591: the namespace is per-install, so these are derived rather than module
    # constants. The hash is a hash of the rendered source, which makes the repair
    # automatic: a tenant seeded under the old hardcoded namespace hashes differently, so
    # it is rewritten here instead of being skipped as already-current.
    mapping_source, compiled_source, compiled_hash = claim_mapping.resolved()
    if items and items[0].get("compiled_hash") == compiled_hash:
        return

    version = (items[0]["version"] + 1) if items else 1
    claims_tbl.put_item(Item={
        "PK": pk,
        "SK": f"VERSION#{version:06d}",
        "gsi1pk": pk,
        "gsi1sk": f"VERSION#{version:06d}",
        "id": str(uuid.uuid4()),
        "tenant_id": tid,
        "version": version,
        "mapping_source": mapping_source,
        "compiled_source": compiled_source,
        "compiled_hash": compiled_hash,
        "compiled_at": now,
        "created_at": now,
        "updated_at": now,
    })


# --------------------------------------------------------------------------- #
# SSM / Secrets Manager
# --------------------------------------------------------------------------- #
def _load_manifest(ssm) -> dict:
    """Read the testbed manifest from SSM.

    This is the bootstrap's configuration, and it lives in the account it configures rather
    than as a GitHub variable: this repo is public, so config held there is unversioned,
    unaudited, and only masked in logs if it happens to be a registered secret. Keeping it
    here also means the invoking workflow needs to know nothing about the testbed beyond
    which environment slot to write.

    ``WithDecryption=True`` unconditionally, so the parameter works as either a String or a
    SecureString. Without it a SecureString returns KMS ciphertext and the JSON parse fails
    with something that looks nothing like the real problem.

    Accepts ``{"platform": {...}, "tenants": [...]}`` or a bare tenants array.
    """
    raw = ssm.get_parameter(Name=TESTBED_CONFIG_PARAM, WithDecryption=True)["Parameter"]["Value"]
    manifest = json.loads(raw)
    return manifest if isinstance(manifest, dict) else {"tenants": manifest}


def _check_secret(secrets, secret_id) -> list:
    """Confirm a password secret exists, without ever being able to read it.

    ``DescribeSecret`` returns metadata only — structurally incapable of returning the value,
    unlike an SSM ``GetParameter`` whose safety depends on a ``WithDecryption`` flag staying
    false. The password itself is created out of band alongside the IdP user, because that
    needs the provider's management API.
    """
    try:
        secrets.describe_secret(SecretId=secret_id)
        return []
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("ResourceNotFoundException", "AccessDeniedException"):
            return [
                f"secret '{secret_id}' does not exist ({code}) — create it alongside the IdP "
                f"user, or logins using this identity will fail"
            ]
        raise


def _write_manifest(ssm, env_scope, seeded, tenants, platform) -> None:
    """Publish the resolved set so the PORTH-494 config and the e2e suite can be generated
    rather than hand-kept.

    Carries the admin email and the secret *name* alongside the ids Porth assigned, so a
    consumer needs only this one parameter to know every testbed identity and where to fetch
    its credential. Never a credential value.
    """
    by_id = {t["tenant_id"]: t for t in tenants if isinstance(t, dict) and t.get("tenant_id")}

    resolved = {
        "env_scope": env_scope,
        "generated_at": _utc_now(),
        "tenants": [
            {
                "tenant_id": r["tenant_id"],
                "porth_org_uuid": r.get("porth_org_uuid"),
                "role_id": r.get("role_id"),
                "admin": {
                    "email": by_id.get(r["tenant_id"], {}).get("admin", {}).get("email"),
                    "password_secret": by_id.get(r["tenant_id"], {})
                                              .get("admin", {}).get("password_secret"),
                },
            }
            for r in seeded
        ],
    }
    if platform:
        resolved["platform"] = {
            "tenant_id": "platform",
            "admin": {
                "email": platform["admin"]["email"],
                "password_secret": platform["admin"]["password_secret"],
            },
        }

    ssm.put_parameter(
        Name=TESTBED_MANIFEST_PARAM,
        Value=json.dumps(resolved),
        Type="String",
        Overwrite=True,
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _env_key(env_scope: str, base: str) -> str:
    """ADR-Z8: fold the environment into the *content* of the partition key, never the KeySchema.
    Mirrors porth_common.providers.aws.repositories.base._env_key."""
    return f"ENV#{env_scope}#{base}" if env_scope else base


def _has_gsi(tbl) -> bool:
    try:
        return any(g["IndexName"] == "gsi1" for g in (tbl.global_secondary_indexes or []))
    except (ClientError, TypeError):
        return False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
