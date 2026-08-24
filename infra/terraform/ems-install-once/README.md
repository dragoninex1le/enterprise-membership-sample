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

## Why one key per service

On a single shared key, `kms:Sign` is not "permission to sign as yourself" — it
is permission to mint context **for any tenant, as any service, to any
audience**. That mattered less when only Porth minted. The callback pattern
(PORTH-617) makes completion functions minters, so on a shared key the class of
verify-only receivers erodes one service at a time, each addition individually
reasonable, until there are none left. UAT-4 witnesses that class.

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

### 1. The deploy passes the ARNs

`deploy.yml` reads both parameters and passes them as `FfugSigningKeyArn` and
`SampleAppSigningKeyArn`. The template then grants:

| principal | grant | on |
|---|---|---|
| `SampleAppFunction` | `kms:Sign` + `kms:DescribeKey` | the sample app's key |
| `FfugFunctionRole` | `kms:Verify` | the sample app's key **and** Porth's |

A receiver needs Verify on **every** key that might legitimately have signed
what arrives, because the verifier follows the token's own `kid`. Miss one and
it fails as `bad_signature` — indistinguishable from forgery, and actually a
missing grant. It is the most misleading failure in this design.

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

## The trust list is fail-closed

An install with no bindings trusts no key and refuses **every** internal call —
including ones that worked yesterday. After this migration, re-run a known
synchronous crossing before relying on anything new. That check is what
separates "the keys are wrong" from "the new thing is wrong".
