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

## After applying — two more steps, and nothing works until both are done

Applying creates the keys and publishes their ARNs to
`/porth/{branch}/infra/signing-key-arn/{service}`. It grants nothing and
registers nothing.

### 1. The deploy passes the ARN

`deploy.yml` reads `/porth/{branch}/infra/signing-key-arn/ffug/response` and
passes it as `FfugResponseSigningKeyArn`.

Nothing grants Sign on it yet — the completion role that signs callbacks arrives
with PORTH-620. The parameter is declared now so the wiring is visible rather
than appearing all at once later.

**Verification is moving local.** Today `FfugFunctionRole` holds `kms:Verify` on
the install key, because the installed porth-common calls `kms:Verify` at
runtime. PORTH-623 replaces that: the trust list carries each key's public key
and receivers check ECDSA-P256 themselves. That deletes the N-by-N Verify grant
matrix and makes the design's most misleading failure impossible — today a
missing Verify grant surfaces as `bad_signature`, indistinguishable from
forgery. Do not remove the grant before the porth-common release that does local
verification; removing it early refuses every crossing.

### 2. The bindings are merged into the trust list

`/porth/{branch}/signing-keys` binds `kid → service_id`, and it is the union of
every participant's bindings — Porth publishes its own for `porth`. Validate
before seeding:

```bash
terraform output -json signing_keys_document > ems-keys.json
```

```bash
python -m porth_common.internal_plane.signing_trust ems-keys.json
```

`kid` is the **concrete key ARN, never the alias**.

That output omits `direction` and `public_key` on purpose. `SigningKeyBinding`
is declared `extra="forbid"`, so a document carrying fields the installed
porth-common does not know does not get ignored — it fails to load, and a trust
list that fails to load refuses every internal call on this install. The values
are ready in the `signing_keys_pending_schema` output; move them across in the
same change that takes the porth-common version which understands them.

## The trust list is fail-closed

An install with no bindings trusts no key and refuses **every** internal call —
including ones that worked yesterday. After this migration, re-run a known
synchronous crossing before relying on anything new. That check is what
separates "the keys are wrong" from "the new thing is wrong".
