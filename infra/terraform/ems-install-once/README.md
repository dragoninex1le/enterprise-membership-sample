# ems-install-once — Terraform

Infrastructure that is created once per install, updated rarely, and destroyed
never. Today that is one thing: the **per-service context-signing keys**.

## Why these are not in `template.yml`

They used to be — Porth's equivalents were, and it cost EMS its Porth stack on
2026-08-15. Resources that outlive the application should not share a
destruction blast radius with code that is redeployed on every release.

CloudFormation's `DeletionPolicy: Retain` is not a substitute. Retention is not
management: a retained key survives a stack delete **orphaned and unaliased**,
which is the state the upgrade log's standing note describes as *"the keys look
absent — they are not, find them by description"*.

## Why not in Porth's `porth-install-once` module

ffug and the sample app are EMS's services. Components has no business knowing
they exist, and even an empty-by-default variable over there would be the shape
of this install leaking into the shared module. Same ruling as the shipped
services-config documents: nothing is set upstream; it is entirely down to the
application that is going to use Porth.

## Why per-direction keys, and why only one

On a single shared key, `kms:Sign` is not "permission to sign as yourself" — it
is permission to mint context **for any tenant, as any service, to any
audience**. That mattered less when only Porth minted. The callback pattern
makes completion functions minters, so on a shared key the class of verify-only
receivers erodes one service at a time, each addition individually reasonable,
until there are none left. UAT-4 witnesses that class.

**A key set is per direction** (PORTH-623). Request authority and response
authority are different kinds of authority, so they are different keys, and a
role holds Sign for at most one `(service, direction)` pair — a compromised
completion path cannot mint a *request* even as its own service.

**Keys are provisioned as roles actually need them, never 2N up front.** Today
this install needs exactly one:

| service | direction | why |
|---|---|---|
| `ffug` | response | ffug signs only when it completes async work and calls back |

Deliberately absent: a request key for the sample app. **The app is not a
service in this model** — the existing install key is its request key, so
minting one here would create a second request authority for the same party
rather than separating anything.

## Bootstrapping the state bucket

Terraform cannot create the bucket that holds its own state:

```bash
aws s3api create-bucket --bucket ems-terraform-state --region us-east-1
```

```bash
aws s3api put-bucket-versioning --bucket ems-terraform-state --versioning-configuration Status=Enabled
```

## Usage

```bash
cp backend.example.hcl backend.ems.hcl
```

Then from this directory:

```bash
terraform init -backend-config=backend.ems.hcl
```

```bash
terraform plan
```

Both `*.hcl` copies and `*.tfvars` are gitignored. The defaults already name the
one key this install needs, so a plan takes no var file.

## What one apply produces

Both keys and both trust documents. There is no registration step, nothing to
run afterwards, and nothing the application deploy does.

| resource | what |
|---|---|
| `aws_kms_key.service_signing["ffug/request"]` | ffug's request key — what the app signs with |
| `aws_kms_key.service_signing["ffug/response"]` | ffug's response key — what the worker signs callbacks with |
| `aws_ssm_parameter.signing_keys["ffug"]` | `services/ffug` — **the** document: status, both addresses, both keys |
| `aws_ssm_parameter.service_signing_key_arn[…]` | the ARN, for the deploy to pass as a stack parameter |
| `aws_iam_role_policy.deploy_role_async_work` | what the deploy role needs to create THIS app's resources |

### The deploy role's grants are ours, not Porth's

Porth's receiving-account bootstrap creates `sample-app-deploy-role`, and that
template is generic: it is instantiated for any receiving product, parameterised
by repo owner and name, and it grants what **every** receiving app needs. It
cannot know what this one creates.

A work queue is not what every app needs. It exists because ffug — EMS's fixture
— has asynchronous work, so the grant that creates it is EMS's. Adding SQS
upstream would widen a shared artifact for one consumer, which is the same shape
as an empty-by-default `signing_keys` variable over there: this install leaking
into the shared module.

Attached rather than owned. `aws_iam_role_policy` puts a separately-named inline
policy beside CloudFormation's, so a bootstrap update does not remove it and this
module does not claim a role it did not create.

**Read the comments on each statement before trimming any of them.** Three are
there because a deploy failed without them, with the run id recorded. One —
`AmendStackRoleTrust` — has never been observed failing, because the rollback
cancelled that resource before CloudFormation attempted it, twice. It is
included because the alternative was a third deploy to find out.

The `SessionPolicyDocuments` statement is the cautionary one. The stack already
wrote `auth-session-policy/ffug-tenant-scoped`, so a second document under the
same prefix looked covered by whatever already permitted the first. It was not:
the live grant names the exact parameter. **"Same prefix, therefore covered" is
reasoning, not evidence**, and it turned one deploy into two.

### One document per service

`/porth/{branch}/services/{service_id}` — not one registry listing everybody
(PORTH-625). A shared document needs every participant merging into it, and one
writer that replaces rather than merges silently removes everyone else's keys.

The pre-0.0.11 single document at `/porth/{branch}/signing-keys` is **dead**. An
install that ran a 0.0.10 deploy will have one; delete it. It is a
plausible-looking document at a plausible-looking path, so the next person
debugging a signing problem will find it, edit it, and watch nothing happen.

```bash
aws ssm delete-parameter --name /porth/dev/signing-keys --region us-east-1
```

### There is one service, and the app is not a second one

`ffug` is the service. `ems-sample-app-{env}` is its front half and
`ems-sample-app-callback-{env}` is its other ingress. Only one of them is named
here:

```
endpoints.request  ->  ems-ffug-${environment}     (where a request goes)
```

The answer's address is not in this document. A requester supplies its own
callback endpoint in the envelope, because a service that several callers use
cannot hold one response address for all of them — `directions.response` named
exactly one, and the second caller collided with the first. What the registry
still holds for a callback is ffug's response KEY, not where the answer lands.

`${environment}` is written literally and substituted by porth-common at resolve
time from the Director's verified environment claim. It has to be, now that EMS
deploys a stack per environment: both declare `PORTH_SERVICE_ID: ffug` and so
share this one document, and a literal name would send one environment's
requests to the other's function. This module runs once and cannot know which
environment is calling; the caller does.

There used to be a second, hand-written `sample-app` document holding Porth's
install key as "the app's request key". It was needed because a token's signer
is looked up by the service the token *claims to be from*, and the app claimed
to be someone else. It cost a second document, a second identity, and an alias
that had to be **constructed by hand** — Porth publishes its key's ARN but no
alias, so the literal `alias/porth-context-{branch}` had to keep agreeing with
Porth's own naming, and would have failed at the first crossing if it ever
stopped.

All of that went with the second identity. `terraform apply` destroys
`/porth/{branch}/services/sample-app`.

**This needs porth-common ≥ 0.0.14.** `ServiceClient` did not pass the call's
direction to the endpoint resolver, so every call resolved `endpoints.default`.
On 0.0.13 the `response` override above is written and never read, and every
completion is delivered to ffug's own request ingress.

The same kid legitimately appears in two documents — Porth registers it under
`porth` for its own use, and it is the app's request key here. The duplicate-kid
guard is *per document* on purpose; what it stops is one key serving both
directions, which would undo the split.

### Why this module writes them, rather than `porth-install signing-key register`

Each document has exactly one owner under PORTH-625, so the merge that command
provides has nothing to merge with here. Its key-spec check — refusing anything
that is not `SIGN_VERIFY`/`ECC_NIST_P256` — is for a CLI handed an arbitrary
ARN, and cannot fail for a key this module created with that spec.

What it does that HCL cannot is validate the result through the runtime's own
loader. That moved to `lambdas/ffug/tests/test_signing_key_document_shape.py`,
which runs in CI — earlier than the command would have, and failing on the pull
request rather than at the first internal call of the day.

The alternative was a step in the application deploy. That was wrong for a
reason worth keeping: it required the deploy role to hold `ssm:PutParameter` on
the trust documents and `kms:GetPublicKey` on a signing key. An app deploy with
write access to *who may speak for whom* is a capability nothing about deploying
an app requires — and if the deploy role still has those grants, revoke them.

Doing it here is also better on the thing that matters most: **the documents
cannot drift from the keys**, because one apply produces both.

### Confirm it took

```bash
aws ssm get-parameter --name /porth/dev/services/ffug --query Parameter.Value --output text
```

### What the operator needs

Whoever runs `terraform apply` needs `kms:GetPublicKey` on both keys — the
public half is captured once, here, which is the whole reason verification can
be local — plus SSM read/write on `/porth/{branch}/services/*` and read on
`/porth/{branch}/infra/*`.

### No `kms:Verify`, anywhere

Verification is local as of porth-common 0.0.11: the document carries the public
half and receivers check ECDSA-P256 themselves. Two things that buys — the N-by-N
Verify grant matrix disappears, and a missing grant can no longer surface as
`bad_signature`, because there is no grant to miss.

KMS is now touched by exactly one runtime operation in the whole design: a
minting role signing with its own key.

## The trust list is fail-closed

An install with no bindings trusts no key and refuses **every** internal call —
including ones that worked yesterday. After this migration, re-run a known
synchronous crossing before relying on anything new. That check is what
separates "the keys are wrong" from "the new thing is wrong".
