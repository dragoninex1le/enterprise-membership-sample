# ffug — the consuming service that proves tenant isolation reaches background work

`ffug` (Welsh, "fake") exists for one reason: the Services Area (ADR-Z11) needs a
**real deployed service** to be tested against. The UAT journeys need a callee
that a caller can invoke, that stores tenant-keyed rows, and that verifies a
context envelope before trusting it. ffug is that callee.

Ruled by Richard 2026-08-04 (PORTH-555); placed in this repo 2026-08-07;
Phase B landed 2026-08-20 (PORTH-587).

## What it demonstrates

On `tenant.created`, **the bus** — not a caller — gives the tenant a random
prime. When the tenant is served, `hash` returns `SHA256(prime : payload)`. Two
tenants sending the same payload get different digests.

That much is a parlour trick. The claim underneath it is not:

> ffug serving tenant A holds an STS session whose `dynamodb:LeadingKeys`
> condition is pinned to `ENV#{env}#TENANT#A`. It **cannot read** B's prime, so
> it cannot compute B's digest. DynamoDB refuses the read. No branch in this
> directory is involved, and the function's execution role holds no DynamoDB
> permission at all to fall back on.

The prime is stored in plaintext and the UAT runner can read every tenant's — by
design, so "two tenants, two salts" is checkable by inspection. It is
tenant-*unique*, not tenant-*exclusive*. The exclusivity is IAM's. Anyone
reading this who concludes the prime is doing the securing has it backwards.

## The boundary rules — a reviewer asserts these

1. **No domain behaviour.** Three ops: `echo` (store a payload under the
   caller's tenant, hand it back), `get` (read it back), `hash` (return this
   tenant's digest of a payload; writes nothing). A change that adds a fourth
   belongs somewhere else, and a feature request against ffug is a smell.

   > **Amended 2026-08-20 (Richard, PORTH-587).** This rule read "the only
   > operations are `echo` and `get`" and PORTH-555's acceptance criteria said
   > "still no business logic beyond echo-with-storage". Both were written
   > before the isolation failures recorded in entries 10–13 of Porth's EMS
   > upgrade log. A fixture that cannot hold per-tenant state cannot demonstrate
   > per-tenant isolation, so `hash` was added deliberately and the rule moved
   > with it. Recorded here rather than quietly broken.

2. **No Porth-internal imports.** ffug depends on `porth-common` and on nothing
   else from the Porth side. It never reaches into Porth internals, tables, or
   private modules.
3. **Portable by construction.** ffug is a **Prawf seed asset** — the future
   unified testbed inherits it. Everything lives under this one directory plus
   its resources in the root `template.yml`, so it can be lifted out whole.
4. **Nothing sensitive in logs.** This repo is public and its Actions logs are
   world-readable (PORTH-533). Log identifiers, never payload bodies, never
   salts, never envelope token contents.

## The two halves

| | |
|---|---|
| `lifecycle.py` | The bus consumer. Maintains the tenant projection from contract-v1 `tenant.*` events — mints the salt on create, refuses service on suspend, purges on delete. Runs with nobody calling ffug. |
| `handler.py` | The request path. Builds a `Director` from the verified context envelope, narrows to the caller's tenant, serves the three ops. |
| `keys.py` | The key shapes. **One** definition, because both of the above write to the same partitions from opposite directions. |
| `salt.py` | Prime minting and the digest. Pure. |

## Phases

**Phase A (2026-08-07).** A bare echo Lambda on plain IAM invoke, one
tenant-keyed table, registered as a service principal in Porth's D3 services
config. No `porth-common` — the point was to prove the deploy path *before*
security-critical code rode it.

**Phase B.** Adopt the libraries as they merge, so every slice gets a live
deployed demonstration instead of a CI-only one:

| Upstream | ffug adopts | Proves live | |
|---|---|---|---|
| PORTH-547 | verify the envelope before trusting it | UAT-4 rejection classes against a real verifier | **done** (PORTH-587) |
| PORTH-550 | Director inside; STS narrowing | TS-MC.2 per-record teardown; cross-tenant denial | **done** (PORTH-587) |
| PORTH-546 | lifecycle subscription: seed on created, purge on deleted | S6 reference consumer, residue-free | **done** (PORTH-587) |
| PORTH-549 | be called via the S5 client, both modes | D7.4 in-install and laptop-SigV4 | open |

`resolve_tenant_context()` was the seam Phase B was going to change. It is gone:
tenant and environment now come from `Director`, off the signed claims.

## Keys

Every row sits under `pk = ENV#{environment}#TENANT#{tenant_id}` (ADR-Z8), so
tenant isolation is a property of the key rather than of a code check — which is
what the `LeadingKeys` condition binds to.

| `sk` | | |
|---|---|---|
| `PROJECTION` | the tenant's status and salt | one bounded row per tenant, non-transient, read by exact key |
| `ITEM#{item_id}` | `echo` rows | transient, purged wholesale on `tenant.deleted` |

## Residue, defined

"Zero residue" (UAT-5) means **no `PROJECTION` row carrying a salt, and no
`ITEM#` rows**. What survives `tenant.deleted` is that same projection row
stripped to a status, a timestamp and a TTL — the order gate that stops a late
pre-deletion event resurrecting the tenant. It holds no tenant data and expires
in seven days. This mirrors `TenantProjection`'s in-memory `_deleted_at`, which
its own `row_count()` also excludes.

Agreed up front (PORTH-587) rather than argued at sign-off.

## Security posture

ffug holds `kms:Verify` and **never** `kms:Sign`. That is deliberate: ffug's
execution role attempting to mint a context token, and being denied, is how the
Sign/Verify split gets witnessed live in UAT-4 (HoS condition H1; Richard's Q10
ruling, 2026-08-05).

The counterpart matters as much. `PorthUatRunnerRole` **can** sign, granted from
this stack's own template — because without a signer in the account, ffug's
denial proves nothing, since everything is denied. That grant, and why Porth's
own dev-class gate did not provide it, is recorded in Components PR #294.

The function's execution role holds **no DynamoDB permission**. The Director
raises rather than proceeding when it cannot narrow, so with no ambient grant a
narrowing failure is an `AccessDenied` instead of silent full-table access.
`test_template_isolation.py` asserts all of this against `template.yml`, because
none of it appears in a code diff.
