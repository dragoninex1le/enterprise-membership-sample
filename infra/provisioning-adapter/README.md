# prawf provisioning adapter — EMS

EMS's implementation of the prawf provisioning contract (ADR-P1, PROVISIONING-CONTRACT v1). prawf owns
the specification; this is the target's implementation (D1). Epic PRF-7; this slice is **PRF-9**.

It is prawf's deliberate backdoor into Porth's data for black-box testing. porth-install is how an
*application* gets configuration and data into Porth; this adapter writes Porth's tables directly,
reinventing what porth-common sometimes provides, and every write it makes is proven by reading back
**through Porth's API** — never by reading DynamoDB (ADR-P1 D4).

## Shape

- **One adapter per target; the slot is chosen per call.** The target owns its slot topology in a slot
  map (`/prawf/adapter/slot-map`); prawf names a slot and the adapter resolves it. Adding a slot is a
  map entry. An adapter per slot would couple prawf to the target's deployment topology.
- **No HTTP surface.** Invoked directly by ARN (§1.1). The event is the request envelope; the return
  value is the response envelope. No API-Gateway wrapping either way.
- **It answers what it implements, and nothing else.** Every other verb returns `unsupported` /
  `not_implemented`, which prawf reads as *skip*.

## The entity catalogue

An entity declares only the verbs it implements — C1 forbids declaring anything else. Implemented:
`seed` and `teardown` on `porth-org`, `porth-tenant`, `porth-claim-mapping` and `porth-role` (PRF-12,
PRF-13, PRF-15, PRF-18); `reset` on `porth-session`; and, in contract 1.1 only, `bootstrap`, `reset` and
`prune` on `porth` (PRF-20). Every other entity declares `verbs: []`. `{s}` is the slot's env_scope;
`{tid}` a tenant id.

## Contract versions

The adapter speaks contract **1.0** and **1.1** (addendum, Confluence 74448898). A caller sending a
three-part version (`1.0.0`, `1.1.0`) speaks the 1.0 schemas and is answered in `1.0.0`, exactly as
before. A two-part caller (`1.0`, `1.1`) is negotiated up to `1.1`, and gets 1.1's additions: a slot
required on every verb that writes or deletes (`slot_required`), `unknown_slot`, `environment {id, slot}`
on every response, `baseline_kind` on each entity, and `prune`. `prawf-schemas` 1.1.0 (released
2026-11-05) holds both versions, and the tests validate every answer, 1.0 or 1.1, against it.

## `porth`: the install's baseline, as a snapshot

`bootstrap` holds no idea of what an install should contain — that changes version to version, and
checking it is the job of post-deploy test scripts (Richard, 2026-11-05). It is called after a deploy,
with the `installed_version` prawf supplies, and copies **every row of the slot** — every row whose
partition key starts `ENV#{s}#` — from Porth's six data tables, verbatim, with each table's key schema,
into the audit table under `ENV#{s}#ENTITY#porth` / `BASELINE#{installed_version}#{content_digest}`.
The digest is sha256 over a canonical form of exactly those rows, so an untouched slot hashes the same
every time. A snapshot too big for its item (gzipped, over 300 KB) goes to the adapter's bucket,
`prawf-adapter-snapshots-{account}`, under `{s}/porth/…`, with the object's hash on the item. Sessions
are not captured: their keys carry no environment.

`prune` deletes the baselines prawf names — a version, or a version and a digest — and nothing else.
The adapter never records which baseline is current, and never chooses one.

## `reset`: back to what was bootstrapped

`reset porth` names the baseline (`payload.baseline {installed_version, content_digest}`). It removes
every row of the slot from those six tables and writes the baseline back, then hashes the slot again and
answers `snapshot_invalid` on a mismatch — as it does for a baseline never stored, or one whose stored
hash no longer matches. What is live is not consulted: whatever a seed or a test changed, the platform
tenant's IdP config included, goes back to what was captured, and a test that needs it seeds it again.
`expected_current_digest` is accepted and not checked. Back to *seeded* is `reset` then `seed` of the
same dataset (PRF-14); the seed entities' ledgers go with their rows, so the same dataset is written
again, not answered `unchanged`. Tenants, organisations and users removed and not written back are
announced with Porth's `deleted` events, which is how Porth's consumers (FFUG) learn they have gone.

The seed entities no longer reset one by one, and reset must name its entity. `reset porth-session`
clears Porth's whole sessions table, every environment's, reading only the keys of what it deletes. A
`protected` slot refuses reset outright (C8); on a disposable one the caller must confirm
`confirm_environment_class` and is refused on a mismatch.

## `porth-org`: seed and teardown

The porth-org ruling, Option A (2026-10-23): an organisation is its own entity, seeded before its
tenants and torn down after them. A seeded organisation is the org half of Porth 0.3.1's
`POST /organizations/` — the org row (slug in `gsi1`) by conditional put, and `Organization.created` —
field for field, since porth-common 0.0.9 has no organisation-only create. An existing slug is never
overwritten; an organisation that still has tenants is not torn down on its own. `teardown` with no
entity removes tenants first. Resource type `porth.org` (an extension type), e.g.
`{"type": "porth.org", "alias": "ems", "spec": {"name": "EMS"}}`.

## `porth-tenant`: seed and teardown

`seed` takes an inline, enumerated dataset (contract §4.3, §8) and writes exactly what **Porth 0.3.1**
— the version EMS runs — writes for `PUT /tenants/`, with **Porth's own code**: porth-common 0.0.9
(pinned in `src/adapter/requirements.txt`) for the tenant row, the tenant-admin role, the tenant
permissions and the role's grants, and their events on Porth's bus. The orchestration of the last
three is Porth 0.3.1's `provision_tenant_admin_role`, which is not in the wheel.

- The dataset's digest is recomputed and a mismatch refused (rule in `datasets.py`).
- Each tenant is validated with Porth 0.3.1's own request model before anything is written: one bad
  row empties Porth's tenant directory and stops every login in the slot.
- The org must exist — seed it as `porth-org` first — and the tenant must not. Nothing is
  overwritten.
- The same dataset again is `unchanged`; a different one is refused until the first is torn down.
- A ledger in **prawf's own audit table** (`prawf-adapter-audit`, never one of Porth's) records every
  write *before* it is made, so `teardown` — by run id — removes a half-finished seed as surely as a
  finished one. It also records which dataset each entity carries. A test tool's bookkeeping does not
  belong in the application's tables (2026-10-25); a full reset removes any an earlier adapter left there.

- The tenant's IdP config (`idp_config_override`, `provider_org_id` included) is part of the tenant:
  it lives on the tenant row, and is set with Porth's own `PATCH /tenants/{id}` path (`update`,
  validated by `TenantPatch`) - Porth 0.3.1's `PUT` accepts it but porth-common 0.0.9's `create` drops it.

Claim mappings are their own table and entity (`porth-claim-mapping`), and nothing here writes to the
identity provider.

## `porth-role`: seed and teardown

An arranged role - one a test needs that the tenant's seed does not make, such as `no-access` for a
denial test (PRF-18). What Porth 0.3.1 writes for `POST /roles/`: `create_role` with `is_system=False`,
never taken from the caller (PORTH-597), so every seeded role is one reset may remove. No grants:
`spec` takes `tenant`, `source_key` and `description` only. The tenant must exist, and the name and
claim value must be free in it (PORTH-226).

## `porth-claim-mapping`: seed and teardown

What Porth 0.3.1 writes for `POST /claim-mapping-configs/?tenant_id=…`, with Porth's own code: the
dataset's `mapping_source` is validated by `MappingSource`, compiled by `compile_mapping_source`, and
saved as the tenant's next version by `ClaimMappingConfigRepository.save` (`ClaimMappingConfig.created`).
The authorizer runs that compiled mapping to turn a token's roles claim into Porth roles - a tenant
without one signs in with no roles (PORTH-479). The tenant must exist (seed `porth-tenant` first) and
have no claim mapping of its own. Teardown with no entity removes it before its tenant. The porth-common
pin moves when a Porth change affects what the seed writes - not on every porth-common release
(Richard, 2026-11-05).

| Entity | Destructive | Porth resources | Planned | Ruled out |
|---|---|---|---|---|
| `porth` | yes | every row under `ENV#{s}#` in tenants, roles, permissions, claim-mapping-configs, users and org-units; `baseline_kind: snapshot` | `bootstrap`, `reset`, `prune` — PRF-20, implemented (contract 1.1) | `seed` (an override; not built yet); `teardown` (nothing here is run-created) |
| `porth-tenant` | yes | tenants `ENV#{s}#TENANT#{tid}` / `METADATA`, its IdP config (`idp_config_override`) included; its roles, grants and permissions | `seed` PRF-12, `teardown` PRF-15 — implemented | |
| `porth-claim-mapping` | yes | claim-mapping-configs `ENV#{s}#TENANT#{tid}` / `VERSION#{n:06d}` | `seed` PRF-13, `teardown` — implemented | |
| `porth-app-permission` | yes | permissions `ENV#{s}#TENANT#{tid}#NS#{app}` / `PERM#{key}` | `seed`, `absent` | |
| `porth-role-grant` | yes | roles `ENV#{s}#TENANT#{tid}#ROLE#{uuid}` / `PERM#{key}` — unioned, never replaced (PORTH-609) | `ensure`, `absent` | |
| `porth-role` | yes | roles `ENV#{s}#TENANT#{tid}` / `ROLE#{uuid}`, not a system role | `seed` PRF-18, `teardown` — implemented | |
| `porth-session` | yes | sessions: the whole table, every environment's | `reset` — implemented | |
| `porth-idp` | no | Auth0 users, Organizations, role assignments | — | every verb: needs the provider's Management API, which is not in this account |

Attribute case is part of the shape: tenants and claim-mapping-configs use `PK`/`SK`; permissions and
roles use `pk`/`sk`.

### Findings against PRF-7's agreed list (§12 — the first real entity catalogue)

- **`porth-idp` was two things.** Porth's *stored record* of an IdP is writable from this account; the
  IdP itself is not. Same name, opposite reachability. The stored record is part of `porth-tenant`
  (2026-10-25: it is an attribute of the tenant row, not an entity); `porth-idp` is the IdP.
- **Two entities the list did not have:** `porth-app-permission` and `porth-role-grant`, the
  application's own layer on top of what Porth installs. Kept separate (one call, one entity, D12) so
  teardown is never ambiguous about which half it undoes.
- **`porth-org` is not declared.** Own entity or tenant attribute is deferred to the live-data
  extraction, not decided here.

## Isolation between slots — IAM, not routing

- The function's role (`ExecutionRole`) has **no DynamoDB access**.
- Every data call assumes `DataRole` with an inline session policy admitting only partition keys under
  `ENV#{slot}#` (`dynamodb:LeadingKeys`, `ForAllValues:StringLike`). A request routed to the wrong slot
  is denied by AWS, not avoided by code. This is the pattern Porth's own Director uses.
- `DataRole` is the ceiling: the four Porth tables named explicitly, single-item writes only.
- **PartiQL is denied outright; Scan is allowed on Porth's six data tables alone** (PRF-20, Richard
  2026-11-05), and on the sessions table to clear it. `ForAllValues` over an absent key evaluates
  *true*, and a Scan carries no LeadingKeys — so IAM cannot hold a Scan to one slot. The scan's filter
  (`snapshot.scan_slot`) drops every other slot's rows inside DynamoDB, before anything is returned,
  so no other environment's row — `prod`'s included — reaches the adapter. Never an index or the audit
  table; denied everywhere else at every layer. Writes stay held to the slot by LeadingKeys.
- **Snapshot objects are held to the slot by prefix**: the session policy admits `{bucket}/{s}/*` only.
- **Tables are named, never `porth-*`.** On main the sample app's own table is
  `porth-sample-app-${PorthEnvironment}`, which matches.
- **Slot names are looked up, never interpolated,** and must match `^[a-z][a-z0-9-]*$` — the session
  policy is a glob, so a slot named `*` would otherwise admit every slot. `ENV#porth-dau#*` does not
  match `ENV#porth-dau-probe#…`.

## No default slot

A call that omits `slot` resolves only when the map has exactly one entry; otherwise it is refused. A
silent default is precisely the failure TAM §2.2 exists to catch. In contract 1.1 every verb that
writes or deletes must name its slot even then (`slot_required`), and an unknown slot is
`unknown_slot`; a 1.0 answer has neither code and says `scope_violation`. The deployed map stays
**single-slot (`porth-dau`)** while 1.0 callers remain, because a 1.0.0 caller cannot name a slot.

## Identity from ground truth

`capabilities` reports the slot's `environment_id` and `environment_class` from the target's own map —
the slot must be in it — never whatever slot it was asked about. It no longer judges whether a slot is
bootstrapped: "the platform tenant row exists" was a guess about what an install contains. A slot is
bootstrapped for prawf when prawf holds a current baseline for its deployed version. `candidate_version`
is the Porth stack's `ImageTag` parameter, which equals the release version (PORTH-657); a
SAR-era stack without it falls back to its `serverlessrepo:semanticVersion` tag.

## Deploying

`.github/workflows/deploy-provisioning-adapter.yml`, dispatch only, GitHub environment
`prawf-adapter`. `bootstrap.yml`, deployed by hand once, holds only what **deploys** the adapter: the
deploy role, the CloudFormation execution role, and `prawf-adapter-boundary` - the scope the pipeline may
grant, by service and resource family (Porth's table families' data plane, Porth's and the adapter's
parameters read-only, Porth's stack read, Porth's event buses, objects in the adapter's own
`prawf-adapter-*` buckets, the adapter's own logs and roles; nothing in IAM). What the adapter may **do**
at runtime is `template.yml`'s, and changes through the pipeline: which actions, the one-slot session,
Scan on Porth's data tables alone, the snapshot bucket, the denials. A runtime change that
stays inside the scope needs no bootstrap deploy; one that does not fails `tests/test_bootstrap.py` in
its PR. The stack creates only its own runtime roles. The cross-account permission is off until PRF-10 sets
`CallerRoleArn`; it deliberately carries **no `aws:SourceAccount` condition** — that key is absent when
a role invokes directly, so the condition would deny every call.

## Tests

```bash
python -m pytest infra/provisioning-adapter/tests -q
```

Offline, with in-memory fakes, and every response is validated against the real schemas from the
`prawf-schemas` package (CodeArtifact `estyn-prawf-py`). `tests/test_porth_tenant.py` runs the real
porth-common 0.0.9 (CodeArtifact `porth/porth-py`) against an in-memory AWS (moto) and reads every
seeded row back through Porth's own repositories and its tenant directory scan. A canary proves the validator can fail. The
C1 test is behavioural: anything the adapter declares must not answer `unsupported`.

## Checking the deployed adapter

`scripts/permutations.py` runs the live function through every case with `aws lambda invoke`: malformed envelopes, version negotiation, slot resolution, the order the checks run in, and every verb against every catalogue entity. Each answer is checked against the outcome and reason code it should get, against the §9 invariants, and against the response schema if `prawf_schemas` is installed. It is read-only, so it is safe against a live slot. Run it with EMS credentials:

```bash
python3 infra/provisioning-adapter/scripts/permutations.py --profile <ems-profile> --report permutations.json
```

`--only version` (or `envelope`, `slot`, `order`, `verb:seed`, …) runs a subset.

After prawf seeds, `scripts/verify_seed.py --profile <ems-profile> --tenant ems-test --org ems` checks the
rows in place — organisation, tenant as Porth 0.3.1 writes it, tenant-admin role and grants, the
dataset markers — and that every row Porth's tenant directory loads is one Porth can read. Read-only;
`--components-profile` also compares against the seeded datasets in prawf's bucket. `tests/test_permutations.py` sends every case through the real handler offline, so the script's expectations cannot drift from the code.
