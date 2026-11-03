# Evidence — the internal plane on EMS

What was demonstrated, on which install, and how to check it rather than believe
it. One section per claim. A claim with no run link and no way to recompute it
is a note, not evidence, and belongs somewhere else.

Install: `enterprise-membership-sample`, branch `dev`.
Three environment axes, and they held **different values** — every line below
picks one, and picking the wrong one fails silently:

| Axis | Value | What it names |
|---|---|---|
| `PorthBranch` | `dev` | which configuration documents are read |
| `PorthEnvironment` | `dev` | which table and function names are used |
| `PorthEnvSlot` | `prod` | the ADR-Z8 data slot in every partition key |

> **Renamed since, 2026-09-01 (PORTH-627).** Every resource name recorded below
> is what those runs actually addressed, and is left as observed — evidence that
> is edited to match today's stack stops being evidence. To reproduce any of it
> on the current install, translate:
>
> | then | now |
> |---|---|
> | `porth-sample-app-dev` | `ems-sample-app-porth-sample` |
> | `porth-sample-app-callback-dev` | `ems-sample-app-callback-porth-sample` |
> | `porth-ffug-dev` | `ems-ffug-porth-sample` |
> | `porth-ffug-worker-dev` | `ems-ffug-worker-porth-sample` |
>
> The three axes are two. `PorthEnvironment` is gone — it suffixed names with a
> value that was not the environment — and `PorthEnvSlot` is `EnvironmentSlot`,
> now `porth-sample` rather than `prod`, so the slot in a partition key is the
> same word as the label in the host a tenant types. `PorthBranch` is unchanged
> and still addresses `/porth/dev/…`.
>
> Two things below are NOT renames and a table cannot translate them:
>
> - **`endpoints.default` is now `endpoints.request`**, and its target is the
>   literal `ems-ffug-${environment}`, substituted per call from the Director's
>   verified claim. Both environments share one `services/ffug` document, so a
>   fixed name there would send one environment's requests to the other's
>   function.
> - **`porth-common >= 0.0.17`**, not `0.0.16` — that substitution is what the
>   bump is for.
>
> The runs recorded below predate both. They are still the runs that happened.

---

## Prerequisites — the state the round trip runs against

These are install steps, not results. Recorded because a reader reproducing the
evidence below needs them true first, and two of them are the kind that fail
closed with a message pointing somewhere else.

| # | Step | Where it lives |
|---|---|---|
| 1 | ffug's **two** signing keys — request and response — created, aliased, public halves read once | `infra/terraform/ems-install-once` (applied by hand) |
| 2 | **One** document at `/porth/dev/services/ffug`: status, one endpoint, both keys | same Terraform |
| 3 | `SAMPLE_APP_CALLBACK_TARGET` on the app function | `template.yml`, `!Ref SampleAppCallbackFunction` |
| 4 | porth-common `>= 0.0.16` in `lambdas/requirements.txt` | repo |

The whole document, as deployed:

```json
{
  "contract_version": 1,
  "endpoints": { "default": { "mode": "invoke", "target": "porth-ffug-dev" } },
  "keys": [
    { "alias": "alias/porth-context-ffug-request-dev",  "direction": "request",  "public_key": "…" },
    { "alias": "alias/porth-context-ffug-response-dev", "direction": "response", "public_key": "…" }
  ],
  "service_id": "ffug",
  "status": "active"
}
```

**Three things that used to be here are deliberately absent**, and a reader
comparing against an older install will notice all three:

- **No `services` or `service-endpoints` monoliths.** One document per service
  replaced them (PORTH-623). Anything still reading the old paths finds nothing
  and fails closed.
- **No `sample-app` document.** The app is not a service on the internal plane —
  it is ffug's front half, and declares `source_service = ffug`.
- **No `directions.response`.** The registry holds no callback addresses at all
  (PORTH-624). The requester supplies its own, which is step 3.

**Step 3 is the one that is easy to miss.** Without it the app refuses to
originate async work rather than guessing, because there is no registry entry to
fall back on — by design. It must name `porth-sample-app-callback-dev`, **not**
`porth-sample-app-dev`: that function is a Mangum handler which cannot read an
invoke event and holds no table grant, so completions delivered there would 500
with nothing written. Using `!Ref` on the function resource rather than a rebuilt
string is what stops the address and the thing at that address disagreeing.

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

**Round trip witnessed:** 2026-08-27 23:16 UTC, `8ccb121`, trace
`2d7c7e454bd546a0b261090a953f5884`, tenant `ems-test`, digest `fea1a4a2670f…`.
Fourteen seconds end to end.

| time | hop | log group | line |
|---|---|---|---|
| 23:16:03.922 | 1 — the app | `porth-sample-app-dev` | `sample_app.fingerprint_queued tenant_id=ems-test` |
| 23:16:03.916 | 2 — ffug ingress | `porth-ffug-dev` | `ffug.served operation=hash_async source_service=ffug` |
| 23:16:03.916 | 2 — ffug ingress | `porth-ffug-dev` | `ffug.queued answering=ffug callback_op=fingerprint-complete` |
| 23:16:18.182 | 3 — the worker | `porth-ffug-worker-dev` | `ffug.worker.completed answering=ffug digest=fea1a4a2670f` |
| 23:16:18.133 | 4 — callback ingress | `porth-sample-app-callback-dev` | `sample_app.callback.correlated outcome=stored_hash_matched` |
| 23:16:18.178 | 4 — callback ingress | `porth-sample-app-callback-dev` | `sample_app.callback.served source_service=ffug` |
| 23:16:18.178 | 4 — callback ingress | `porth-sample-app-callback-dev` | `sample_app.fingerprint_completed record_type=invoice digest=fea1a4a2670f` |

**Four log groups. One `trace_id`, unchanged, in every line.** That is the AC,
and it is the assertion — not "each service logged something".

`ffug.worker.batch received=1 failed=0 refused=0`.

### The match is stated, not inferred (AC3)

`sample_app.callback.correlated … outcome=stored_hash_matched`.

It matters because of what it replaced: a mismatch logged a refusal and a match
logged nothing, so success was read from the *absence* of a refusal. That is the
same silence-as-success shape that hid the muted logger for four stories.

What matched is the correlation hash H the app committed **before** the work was
requested, against Porth's recomputation of H from the callback's own verified
`aud`. H never travels. It is computed twice, in two processes, and the two
agree or the completion is refused.

### The registry did not know where the answer went

This is the load-bearing line of the whole run:

```
porth.plane.resolved service_id=ffug path=/porth/dev/services/ffug found=yes
                     status=active endpoints=[default=porth-ffug-dev]
                     signing_aliases=[request=alias/porth-context-ffug-request-dev,
                                      response=alias/porth-context-ffug-response-dev]
```

**One address.** No `directions.response`, because
`/porth/{branch}/services/{id}` no longer holds callback addresses at all
(PORTH-624). And the completion still arrived at
`porth-sample-app-callback-dev` — because the app supplied that address when it
asked, from `SAMPLE_APP_CALLBACK_TARGET`.

Porth holds identity and keys. Where a requester receives answers is the
requester's own business, and it is the one participant that certainly knows
it. Both signing aliases are still in the document and still did their job: ffug
signed the completion with its response key and the callback ingress verified
against it.

That the supplied address is never validated is deliberate. Checking it against
a registered one would make the value redundant and put a lookup on the hot
path. What makes it safe is that the address is not the authority — the envelope
is minted for the VERIFIED `source_service`, so an answer delivered to the wrong
ingress carries the wrong `aud` and is refused before its payload is read.
Asserted in Components `test_a_misdirected_answer_is_refused_by_the_RECEIVER`,
not here: EMS has one requester, so it cannot demonstrate misdirection.

### One service, spelled one way

Every line reads `source_service=ffug` — at ffug's ingress and at the callback
ingress. There is no `sample-app` identity on the internal plane: the app is
ffug's front half, `/porth/dev/services/sample-app` is deleted, and one document
describes the whole conversation.

### The install says where it read, at INFO

All four functions emitted `porth.plane.identity service_id=ffug branch=dev
environment=dev document=/porth/dev/services/ffug` on first invocation, and
`porth.plane.resolved` on first load. `PorthCommonLogLevel` is `INFO` — these are
deliberately not behind DEBUG, because a post-deploy check that needs a redeploy
to switch on is only available to someone who already suspects a problem.

`environment=prod` appears on `ffug.served` beside `branch=dev`, and both were
correct: different axes. `PORTH_BRANCH` selects the configuration path, and the
data environment was fixed at `prod` by the install's `FixedEnvironment`.

That is the half PORTH-627 changed, and it is worth being exact about because
the line above still reads the same way. `FixedEnvironment` is now EMPTY, which
IS multi-environment mode: nothing pins the slot, and `environment=` on that
line is whatever the Director resolved from the signed envelope — `porth-sample`
here, `porth-dau` on the other deployment. The two axes are still two; one of
them simply stopped being a deployment constant and became a per-request claim.

### An earlier run, kept because its accident proved something

The run above is clean — fourteen seconds, no redelivery. **This section
describes a different one**, on 2026-08-25 (trace
`e7e9b9ca576041ffb1e8201bfc5f2481`), and it is kept rather than replaced because
a clean run cannot show what that one showed.

Twenty-four minutes separated acceptance from completion, because the worker
failed four times on a misconfigured signing direction and succeeded on the
**fifth and last** delivery before the dead-letter queue would have taken it.

That is a far better demonstration than the clean run would have been. A token
minted at 05:35 was dead by 05:40 — `MAX_TOKEN_LIFETIME_SECONDS` is 300. The
work completed at 05:59 regardless, because what rides the queue is a
`PersistedContext` and not an envelope. **The whole argument for that decision
was demonstrated by a bug.**

It also witnesses the redrive contract end to end: four failures each returned
the record as a batch item failure rather than deleting it, `maxReceiveCount: 5`
bounded the retries, and the message was still there to succeed when the fix
landed.

### The ordering that broke the attempt before this one

An approval at 22:25:43 the same evening failed, and the cause is worth keeping
because it will recur on any install that carries configuration beside code.

`terraform apply` had already removed `directions.response`. The deploy carrying
the code that stops needing it was **still in flight**. For about three minutes
the install held new configuration and old code, and old code resolves the
callback address from the registry:

```
ffug.worker.failed … invoke of 'ffug' failed: AccessDeniedException …
  not authorized to perform: lambda:InvokeFunction on … function:porth-ffug-dev
```

With no override to find, it fell back to `endpoints.default` and tried to
deliver the answer to ffug's own request ingress. **IAM refused it** — the
worker holds `InvokeFunction` on the callback function and nothing else — so a
misrouted completion failed closed instead of looping. That grant was written
for a different reason and caught this one.

Two lessons, both recorded rather than fixed:

- **Configuration and code are a two-phase change.** Remove a value only after
  the code that stops reading it is live; add one before. Neither ordering is
  safe in both directions.
- **The queue is a version boundary.** The message queued at 22:25 was written
  by the previous ffug and carried no `callback.endpoint`, so it could never
  succeed under the new worker. It now produces a named refusal
  (`ffug.worker.unprocessable … reason=message_predates_callback_endpoint`)
  rather than a `KeyError` in a traceback, four times over.

### What is NOT witnessed here, and why

**The digest has not been recomputed by hand.** Delivery, correlation and
addressing are all proven above; the *arithmetic* is still taken on the app's
word — `fea1a4a2670f…` is what the app says ffug returned, not something checked
independently.

Logs carry a twelve-character prefix only (PORTH-533), so closing this needs the
prime, the document and the full digest from the approvals screen, run through
the same one-liner Claim 1 uses. The async path hashes identically; there is no
second recipe. **PORTH-622 is not complete until that is done.**

**Misdirection is not demonstrated on EMS**, and cannot be. It needs a second
requester supplying a third party's address, and this install has one requester.
The property is asserted in Components
(`test_a_misdirected_answer_is_refused_by_the_RECEIVER`) instead.

**A chain is not demonstrated on EMS either.** `alpha → ffug → gamma` unwinding
back through ffug to alpha is covered by the Components tests; EMS has no middle
hop to witness it with.

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
