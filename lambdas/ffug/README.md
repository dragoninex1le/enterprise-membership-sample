# ffug — the deliberately dumb consuming service

`ffug` (Welsh, "fake") exists for exactly one reason: the Services Area (ADR-Z11)
needs a **real deployed service** to be tested against. The UAT journeys need a
callee that a caller can invoke, that stores tenant-keyed rows, and that will
later verify a context envelope. ffug is that callee and nothing more.

Ruled by Richard 2026-08-04 (PORTH-555); placed in this repo 2026-08-07.

## The boundary rules — a reviewer asserts these

1. **No business logic.** The only operations are `echo` (store a payload under
   the caller's tenant and hand it back) and `get` (read it back). If a change
   adds domain behaviour, the change belongs somewhere else. A feature request
   against ffug is a smell.
2. **No Porth-internal imports.** ffug may depend on `porth-common` once Phase B
   adopts it, and on nothing else from the Porth side. It never reaches into
   Porth internals, tables, or private modules.
3. **Portable by construction.** ffug is a **Prawf seed asset** — the future
   unified testbed inherits it. Everything lives under this one directory plus
   its resources in the root `template.yml`, so it can be lifted out whole.
4. **Nothing sensitive in logs.** This repo is public and its Actions logs are
   world-readable (PORTH-533). Log identifiers, never payload bodies, never
   credentials, never envelope token contents.

## Phases

**Phase A (now).** A bare echo Lambda on plain IAM invoke, one tenant-keyed
DynamoDB table, registered as a service principal in Porth's D3 services config.
No `porth-common` yet — the point is to prove the deploy path *before*
security-critical code rides it.

**Phase B (as each library merges).** ffug adopts them one at a time, so every
slice gets a live deployed demonstration instead of a CI-only one:

| Upstream | ffug adopts | Proves live |
|---|---|---|
| PORTH-547 | verify the envelope before trusting it | UAT-4 rejection classes against a real verifier |
| PORTH-549 | be called via the S5 client, both modes | D7.4 in-install and laptop-SigV4 |
| PORTH-550 | Director inside; STS narrowing; batch path | TS-MC.2 per-record teardown; cross-tenant denial |
| PORTH-546 | lifecycle subscription: seed on created, purge on deleted | S6 reference consumer, residue-free |

`resolve_tenant_context()` in `handler.py` is the seam Phase B changes: today it
reads tenant and environment off the payload, then it will derive them from the
verified KMS-signed token. Both are mandatory today with no fallback, so the
fail-closed posture does not have to be retrofitted.

## Keys

Rows follow the ADR-Z8 shape — `pk = ENV#{environment}#TENANT#{tenant_id}`,
`sk = ITEM#{item_id}` — so tenant isolation is a property of the key, not of a
code check.

## Security posture in Phase A

ffug holds `kms:Verify` and **never** `kms:Sign`. That is deliberate: ffug's
execution role attempting to mint a context token, and being denied by the key
policy, is how the Sign/Verify split gets witnessed live in UAT-4 (HoS condition
H1; Richard's Q10 ruling, 2026-08-05).
