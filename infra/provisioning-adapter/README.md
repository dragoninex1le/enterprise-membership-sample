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

An entity declares only the verbs it implements — C1 forbids declaring anything else. Each slice flips
one cell of the verb × entity matrix: so far `seed` and `teardown` on `porth-org` and `porth-tenant`
(PRF-12, PRF-15), `bootstrap` on `porth-platform` (PRF-11), and `reset` on `porth-claim-mapping`,
`porth-tenant` and `porth-org` (PRF-14); every other entity declares `verbs: []`. `{s}` is the slot's
env_scope; `{tid}` a tenant id.

## `porth-platform`: bootstrap

The baseline is what EMS's Porth install writes — `scripts/bootstrap_platform_tenant.py`, then the
IdP step of `porth-bootstrap.yml`: the platform organisation and tenant (`role_type =
platform-admin`), the ten `porth-platform` permissions, the `platform-admin` role and its grants of
them, the platform claim mapping (roles claim namespaced by the install's audience), and the platform
tenant's `idp_config_override` read back from `/porth/auth`. `bootstrap` reads each piece and writes
only what is missing or differs, so a slot the install bootstrapped answers `unchanged` throughout.
`tests/test_porth_platform.py` runs the install script itself on moto and holds the adapter to it,
row for row. A grant from another namespace on `platform-admin` is the app's (PORTH-609) and is never
removed. The baseline is no run's fixture: teardown never removes it, reset never touches it.

## `reset`: back to the baseline

What §8.4 sends a caller to when a seed meets data it did not write. Reset returns an entity to its
bootstrapped state — whoever wrote what is there — and leaves the platform baseline untouched (C12,
C16): `porth-claim-mapping` loses every tenant's claim mappings but the platform's; `porth-tenant`
every tenant but the platform, with its roles, grants (both key shapes) and permissions;
`porth-org` every organisation but the platform's, refused while tenants still belong to one. With
no entity, all three in that order. A `protected` slot refuses it outright (C8); on a disposable one
the caller must confirm `confirm_environment_class` and is refused on a mismatch. Users, org-units
and sessions are outside the adapter's grant and are named in the response, not passed over.

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
- A ledger beside Porth's rows (keys Porth never reads) records every write *before* it is made, so
  `teardown` — by run id — removes a half-finished seed as surely as a finished one.

IdP settings and claim mappings are other entities (`porth-idp-config`, `porth-claim-mapping`), and
nothing here writes to the identity provider. When EMS moves to a newer Porth, the porth-common pin
moves with it.

| Entity | Destructive | Porth resources | Planned | Ruled out |
|---|---|---|---|---|
| `porth-platform` | no | tenants `ENV#{s}#ORG#{uuid}` and `ENV#{s}#TENANT#platform` / `METADATA`; permissions `ENV#{s}#TENANT#platform#NS#porth-platform`; roles `platform-admin` and its grants; its claim mapping | `bootstrap` — PRF-11, implemented | `reset` (breaks every sign-in); `seed` (the baseline is the target's, D7); `teardown` (nothing here is run-created) |
| `porth-tenant` | yes | tenants `ENV#{s}#TENANT#{tid}` / `METADATA`; its roles, grants and permissions | `seed` PRF-12, `reset` PRF-14, `teardown` PRF-15 — implemented | |
| `porth-idp-config` | yes | tenants `ENV#{s}#TENANT#{tid}` / `METADATA`, attribute `idp_config_override` | `seed`, `reset` | |
| `porth-claim-mapping` | yes | claim-mapping-configs `ENV#{s}#TENANT#{tid}` / `VERSION#{n:06d}` | `reset` PRF-14 — implemented; `seed` PRF-13 | |
| `porth-app-permission` | yes | permissions `ENV#{s}#TENANT#{tid}#NS#{app}` / `PERM#{key}` | `seed`, `absent` | |
| `porth-role-grant` | yes | roles `ENV#{s}#TENANT#{tid}#ROLE#{uuid}` / `PERM#{key}` — unioned, never replaced (PORTH-609) | `ensure`, `absent` | |
| `porth-role` | yes | roles `ENV#{s}#TENANT#{tid}` / `ROLE#{uuid}` | `ensure`, `absent` — PRF-18 | |
| `porth-idp` | no | Auth0 users, Organizations, role assignments | — | every verb: needs the provider's Management API, which is not in this account |

Attribute case is part of the shape: tenants and claim-mapping-configs use `PK`/`SK`; permissions and
roles use `pk`/`sk`.

### Findings against PRF-7's agreed list (§12 — the first real entity catalogue)

- **`porth-idp` was two things.** Porth's *stored record* of an IdP is writable from this account; the
  IdP itself is not. Same name, opposite reachability. Split into `porth-idp-config` and `porth-idp`.
- **Two entities the list did not have:** `porth-app-permission` and `porth-role-grant`, the
  application's own layer on top of what Porth installs. Kept separate (one call, one entity, D12) so
  teardown is never ambiguous about which half it undoes.
- **`porth-tenant` and `porth-idp-config` share one DynamoDB item.** Both must write with `UpdateItem`
  on disjoint attributes — a `PutItem` from either erases the other's half of the row. This is the
  sharpest test so far of §3.3's granularity guidance: one logical row, two addressable entities.
- **`porth-org` is not declared.** Own entity or tenant attribute is deferred to the live-data
  extraction, not decided here.

## Isolation between slots — IAM, not routing

- The function's role (`ExecutionRole`) has **no DynamoDB access**.
- Every data call assumes `DataRole` with an inline session policy admitting only partition keys under
  `ENV#{slot}#` (`dynamodb:LeadingKeys`, `ForAllValues:StringLike`). A request routed to the wrong slot
  is denied by AWS, not avoided by code. This is the pattern Porth's own Director uses.
- `DataRole` is the ceiling: the four Porth tables named explicitly, single-item writes only.
- **PartiQL is denied outright; Scan is allowed on the tenants table alone** (PRF-14, Richard
  2026-10-24). `ForAllValues` over an absent key evaluates *true*, and a Scan carries no LeadingKeys —
  so a Scan reads every slot's rows in that table. Reset needs it: Porth's own tenant directory finds
  tenants by scanning, and a tenant written without Porth's list index (the old qa-tools seeder never
  wrote gsi2) is still one every login loads. Read only, the tenants table only — never an index or
  another table, denied everywhere else at every layer — and `reset.scan_slot` filters to the slot
  before anything acts on a row. Writes stay held to the slot by LeadingKeys.
- **Tables are named, never `porth-*`.** On main the sample app's own table is
  `porth-sample-app-${PorthEnvironment}`, which matches.
- **Slot names are looked up, never interpolated,** and must match `^[a-z][a-z0-9-]*$` — the session
  policy is a glob, so a slot named `*` would otherwise admit every slot. `ENV#porth-dau#*` does not
  match `ENV#porth-dau-probe#…`.

## No default slot

A call that omits `slot` resolves only when the map has exactly one entry; otherwise it is refused. A
silent default is precisely the failure TAM §2.2 exists to catch. The deployed map is **single-slot
(`porth-dau`) until PRF-19 publishes contract 1.1.0**, because a 1.0.0 caller cannot name a slot.
Until PRF-19 adds its own reason code, an unknown slot is refused with `scope_violation`.

## Identity from ground truth

`capabilities` reports the slot's `environment_id` and `environment_class` from the target's own map,
and only once the slot is proven real: its platform tenant row must exist under `ENV#{s}#`, or the
answer is `refused`. It never reports back whatever slot it was asked about. `candidate_version` is the
Porth SAR stack's `serverlessrepo:semanticVersion` tag.

## Deploying

`.github/workflows/deploy-provisioning-adapter.yml`, dispatch only, GitHub environment
`prawf-adapter`. The deploy and CloudFormation execution roles are created by hand, outside this repo, from
drafted policy documents; the stack creates only its own runtime roles. The cross-account permission is off until PRF-10 sets
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
