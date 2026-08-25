# Evidence — the internal plane on EMS

What was demonstrated, on which install, and how to check it rather than believe
it. One section per claim. A claim with no run link and no way to recompute it
is a note, not evidence, and belongs somewhere else.

Install: `enterprise-membership-sample`, branch `dev`.
Three environment axes, and they hold **different values** — every line below
picks one, and picking the wrong one fails silently:

| Axis | Value | What it names |
|---|---|---|
| `PorthBranch` | `dev` | which configuration documents are read |
| `PorthEnvironment` | `dev` | which table and function names are used |
| `PorthEnvSlot` | `prod` | the ADR-Z8 data slot in every partition key |

---

## Prerequisites — the state the round trip runs against

These are install steps, not results. Recorded because a reader reproducing the
evidence below needs them true first, and two of them are the kind that fail
closed with a message pointing somewhere else.

| # | Step | Where it lives |
|---|---|---|
| 1 | Per-direction signing keys created, aliased, public keys read once | `infra/terraform/ems-install-once` (applied by hand) |
| 2 | Trust documents written, **one per service**, at `/porth/dev/signing-keys/{service_id}` | same Terraform |
| 3 | `sample-app` and `ffug` active in `/porth/dev/services` | seeded CREATE-ONLY by `porth-install` |
| 4 | `ffug` **and `sample-app`** in `/porth/dev/service-endpoints` | operator |
| 5 | porth-common `>= 0.0.11` in `lambdas/requirements.txt` | repo |

**Step 4 is the one that is new.** Until PORTH-621 nothing had ever called
*into* this app, so it never needed an endpoint entry. Without one, ffug's
worker resolves the callback target, finds nothing, and every completion fails
in the drainer rather than at the app — the message names a parameter and not
the round trip that wanted it.

The `sample-app` entry must point at `porth-sample-app-callback-dev`, mode
`invoke`. **Not** `porth-sample-app-dev`: that function is a Mangum handler
which cannot read an invoke event and holds no table grant, so completions
delivered there would 500 with nothing written.

---

## Claim 1 — the synchronous round trip (PORTH-587, PORTH-599)

An approval in the sample app calls ffug lambda-to-lambda; ffug takes the tenant
from a KMS-signed envelope, narrows an STS session to it, reads **that tenant's**
prime and returns a digest.

**Witnessed:** 2026-08-24, deploy `a88908e`, run
[`32804178837`](https://github.com/dragoninex1le/enterprise-membership-sample/actions/runs/32804178837).

**How to check it rather than believe it.** The screen shows all three of the
document, the prime and the digest, precisely so the claim is checkable:

```
document {"record_type":"invoice","record_id":"…","counterparty":"…","amount":"…"}
primed with 17750909304574187717
sha256    dc1c94f0…
```

Recompute it:

```bash
python3 -c 'import hashlib,json,sys; d=json.loads(sys.argv[1]); print(hashlib.sha256((sys.argv[2]+":"+json.dumps(d,separators=(",",":"),sort_keys=True)).encode()).hexdigest())' '<document>' '<prime>'
```

What the match proves is narrower than "ffug works", and the narrow version is
the point: **this tenant's prime produced this number, and no other tenant's
could**, because ffug serving another tenant cannot read this prime. The prime
was minted by `lifecycle.py` off the bus on `tenant.created` — the request path
can read it and cannot create it.

---

## Claim 2 — the asynchronous round trip (PORTH-620, PORTH-621, PORTH-622)

**Infrastructure deployed:** 2026-08-25, `25f92ca`, run
[`32810298045`](https://github.com/dragoninex1le/enterprise-membership-sample/actions/runs/32810298045)
(attempt 2). Queue, dead-letter queue, worker, event source mapping, callback
ingress and its role, the callback session-policy document, and the amended
trust on `SampleAppTenantRole` — all `CREATE_COMPLETE`/`UPDATE_COMPLETE`.

*The round trip itself is not yet witnessed. Everything below is the recipe, and
it becomes evidence when the trace is followed live.*

### What it took to deploy, recorded because it will happen again

Three attempts, and the first two are worth keeping rather than tidying away.
Each failure was a permission the receiving deploy role did not hold, because
this stack introduced resource types it had never created:

| run | denied | note |
|---|---|---|
| `32806570360` | `sqs:CreateQueue` | SQS was a wholly new resource type — nothing covered it even partially |
| `32807678711` | `ssm:PutParameter` | on the callback's session-policy document |
| `32810298045` #1 | `ssm:PutParameter` again | the grant had been applied, but *after* this run passed that resource |

The second one is the lesson. It was predicted as *covered* on the reasoning
that the stack already writes `auth-session-policy/ffug-tenant-scoped` under the
same prefix — but the live grant names the exact parameter, so a sibling
document was a new resource entirely. **"Same prefix, therefore covered" is
reasoning, not evidence.**

The grants now live in `infra/terraform/ems-install-once` rather than in Porth's
receiving-account template, and the distinction is the same one that governs the
signing keys: that template is generic, instantiated for any receiving product,
and grants what every receiving app needs. A work queue exists because ffug has
asynchronous work, so the grant that creates it is EMS's.

Approve a record. Expected sequence:

| Stage | Where | What to look for |
|---|---|---|
| accepted | `porth-sample-app-dev` | `sample_app.fingerprint_queued … trace_id=…` |
| queued | `porth-ffug-dev` | `ffug.served operation=hash_async` |
| drained | `porth-ffug-worker-dev` | `ffug.worker.hashed`, then `ffug.worker.completed` |
| completed | `porth-sample-app-callback-dev` | `sample_app.fingerprint_completed` |

**One `trace_id` across all four.** That is the whole correlation story: the app
minted it, hashed it into the record, and sent it; ffug persisted it with the
context rather than with a token; the worker sent it back; the callback matched
it against what the app stored. If it changes anywhere, the design has a second
identity for one request and correlation means nothing.

With `FfugLogLevel=DEBUG`, `ffug.narrowed` shows the worker narrowing **per
record** — the property that a batch carrying several tenants gets one Director
each, and the reason `PerRecordDirectors` exists rather than a loop.

The digest recomputes exactly as in Claim 1, from the same three values on the
same screen. Nothing about the asynchrony changes what is being proven; it
changes only when the answer arrives.

---

## Claim 3 — what is NOT on the queue

Assertable without a deployment, which is why it is a test rather than a run
link: `test_the_queued_message_carries_no_token_and_no_envelope`.

The queued message carries a `PersistedContext` and no signed token. A token
minted for a crossing that already finished proves nothing about the delivery
carrying it, and keeping one valid long enough to survive a redrive would mean
moving `MAX_TOKEN_LIFETIME_SECONDS` — an H2 change, for no gain.

The persisted record needs no signature for the same reason a row in ffug's own
table needs none: only ffug's verified ingress writes where it lives.

---

## Claim 4 — the isolation properties that live in IAM

Behaviour that lives in a permission does not appear in a code diff, so these are
asserted against `template.yml` on every PR and every deploy rather than read:
`lambdas/ffug/tests/test_template_isolation.py`.

| Property | Why it is worth an assertion |
|---|---|
| ffug's request path holds **no KMS at all** | It verifies and can never mint. UAT-4 witnesses the denial live; adding Sign here would delete the demonstration, not merely widen a permission |
| Only the worker role holds `kms:Sign`, on ffug's **response** key | A completing service cannot originate work — the capability is absent rather than unused |
| The callback ingress holds **no KMS at all** | The mirror. It receives and originates nothing |
| Nothing anywhere holds `kms:Verify` | Verification is local as of porth-common 0.0.11. A Verify grant means something is calling KMS at verify time again |
| No role holds standing DynamoDB except the lifecycle consumer | Narrowing is only a boundary while there is nothing underneath it. The consumer is the documented exception: no envelope ever runs for an EventBridge delivery, so its execution role is the only identity it has |
| `Scan` appears in neither the role nor the session policy | It populates no `dynamodb:LeadingKeys`, so `ForAllValues:StringLike` passes **vacuously** against it. Granted anywhere in the pair it would read as tenant-scoped and reach every tenant |

That last one is the sharpest lesson of the whole exercise and cost a day:
**IAM authorizes requests, it never filters responses.** An unfiltered `Scan`
cannot demonstrate the Director, in either direction — it is blind to narrowing
working and blind to it failing. The test that proves narrowing is a refusal the
*role* would have allowed, which is why `isolation_probe` aims a `BatchGetItem`
at a partition that really exists rather than at an empty one: a denial against
nothing can be read as "there was nothing there anyway".
