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

Both `*.hcl` copies and `*.tfvars` are gitignored. The defaults already name
EMS's two minting services, so a plan needs no var file.

## After applying — register the keys, once

Applying creates the key and publishes its ARN. It registers nothing, and
**neither does the deploy**. Registration is an install-once step, run
deliberately alongside this module — not on every application deploy.

That is the same reason the keys are here rather than in `template.yml`: a key
and its registration outlive the code, and anything that runs on every release
is one bad release away from rewriting them. An app deploy has no business
holding `ssm:PutParameter` on the trust documents or `kms:GetPublicKey` on a
signing key.

Two registrations, and the second is the one that is easy to miss.

| document | key | direction | why |
|---|---|---|---|
| `signing-keys/sample-app` | the **install** key | request | the app claims `sample-app` and signs with the install key |
| `signing-keys/ffug` | ffug's own key | response | ffug signs only when it calls back |

```bash
pip install 'porth-install>=0.3.2'
```

```bash
porth-install signing-key register --service sample-app --direction request --branch dev --key-arn "$(aws ssm get-parameter --name /porth/dev/infra/context-signing-key-arn --query Parameter.Value --output text)"
```

```bash
porth-install signing-key register --service ffug --direction response --branch dev --key-arn "$(terraform output -raw -json signing_key_arns | python3 -c 'import json,sys; print(json.load(sys.stdin)["ffug/response"])')"
```

The command resolves the ARN (an alias is a valid thing to hand it and an
invalid thing to store), refuses a key that is not
`SIGN_VERIFY`/`ECC_NIST_P256`, captures the public half with
`kms:GetPublicKey`, merges into whatever is already there, and validates the
result through the same code the runtime loads it with — so a document it
refuses can never reach a verifier. It is idempotent: re-running replaces the
entry in place rather than duplicating it.

Verification resolves `(kid, source_service, direction)` by fetching the
document of the service the token **claims to be from**. So the install key must
appear under `sample-app` — without it every crossing that works today fails
with `UnknownSigningServiceError`.

The same kid legitimately appears in two documents: Porth registers it under
`porth` for its own use, and it is the app's request key here. The duplicate-kid
guard is *per document* on purpose — what it stops is one key serving both
directions, which would undo the split.

### Confirm it took

```bash
aws ssm get-parameter --name /porth/dev/signing-keys/sample-app --query Parameter.Value --output text
```

### One document per service

`/porth/{branch}/signing-keys/{service_id}` — not one registry listing everybody
(PORTH-625). A shared document needs every participant merging into it, and one
pipeline that *writes* rather than merges silently removes everyone else's keys.

The pre-0.0.11 single document at `/porth/{branch}/signing-keys` is **dead**. If
an install ran a 0.0.10 deploy it will have one; delete it. It is a
plausible-looking document at a plausible-looking path, so the next person
debugging a signing problem will find it, edit it, and watch nothing happen.

```bash
aws ssm delete-parameter --name /porth/dev/signing-keys --region us-east-1
```

EMS never adopted 0.0.10, so EMS should not have one.

### Two registrations, not one

The deploy registers **two** keys, and the second is the one that is easy to
miss.

| document | key | direction | why |
|---|---|---|---|
| `signing-keys/sample-app` | the **install** key | request | the app claims `sample-app` and signs with the install key |
| `signing-keys/ffug` | ffug's own key | response | ffug signs only when it calls back |

Verification resolves `(kid, source_service, direction)` by fetching the document
of the service the token **claims to be from**. So the install key must appear
under `sample-app` — without it every crossing that works today starts failing
with `UnknownSigningServiceError`, because nothing else creates that document.

The same kid legitimately appears in two documents: Porth registers it under
`porth` for its own use, and it is the app's request key here. The duplicate-kid
guard is *per document* on purpose — what it stops is one key serving both
directions, which would undo the split.

### What the operator needs

Registration calls KMS and writes SSM, so whoever runs it needs
`kms:DescribeKey` and `kms:GetPublicKey` on the keys, and `ssm:GetParameter` +
`ssm:PutParameter` on `/porth/{branch}/signing-keys/*`.

**The deploy role does not need any of it.** If it was granted for an earlier
version of this that ran registration from the pipeline, revoke it — an app
deploy with write access to the trust documents is one bad release away from
rewriting who may speak for whom.

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
