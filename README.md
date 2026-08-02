# enterprise-membership-sample

A public example demonstrating how to build an admin UI that consumes [porth-common](https://github.com/dragoninex1le/Components) — the Porth multi-tenant login component.

This repository shows the **portability** of `porth-common` without exposing its source code. It deploys a full-stack React + AWS admin interface into the same AWS account as the component.

## What this demonstrates

- Consuming the Porth REST API (41 endpoints across 7 domains)
- Multi-tenant user, role, permission, and claim mapping management
- Auth0 integration for real IdP authentication
- End-to-end: JWT → claim mapping → role resolution → permission check
- Extracting reusable components as `@porth/ui`

## Architecture

```
[ Auth0 ] ──JWT──▶ [ React SPA (S3/CloudFront) ] ──▶ [ Porth API (Lambda/API Gateway) ]
                                                              │
                                                      [ DynamoDB tables ]
```

## Stack

- **Frontend:** React 18, Vite, TypeScript, Tailwind CSS
- **Auth:** Auth0 (`@auth0/auth0-react`)
- **Infrastructure:** AWS SAM — S3 + CloudFront (frontend), Lambda + API Gateway (backend in Components repo)
- **CI/CD:** GitHub Actions — build → S3 upload → CloudFront invalidation

## Prerequisites

- Node 20+
- AWS CLI + SAM CLI configured
- Auth0 free account
- The [Components](https://github.com/dragoninex1le/Components) stack deployed (provides `PORTH_API_URL`)

## Local development

```bash
cd frontend
npm install
cp .env.example .env.local   # fill in the API URLs and tenant
npm run dev
```

## Deployment

```bash
sam deploy --guided
```

In CI, deployment runs through **Deploy Admin UI** rather than `sam deploy --guided`.

## Workflows

Each runs under a GitHub Environment that supplies the AWS OIDC role — there are no
long-lived AWS credentials in this repo.

| Workflow | Environment | Purpose |
|---|---|---|
| **Deploy Admin UI** | `sample-app-deploy` | Builds the SPA, deploys the sample-app stack, syncs S3, invalidates CloudFront |
| **Porth components — install + upgrade** | `porth-install` | Installs/upgrades the Porth SAR app and bootstraps the platform tenant |
| **Deploy Porth QA Tools** | `porth-install` | Deploys the cleanup + seed Lambdas (`porth-qa-tools`) |
| **Reset Dev Environment** | `porth-install` | Clears all tenant data, re-bootstraps the platform tenant |
| **Porth — seed testbed tenants** | `porth-install` | Seeds the synthetic tenants used by Tier 2 e2e and the PORTH-494 lab |
| **E2E Tests** | — | Tier 1 (mocked) on every push; Tier 2 (live) after a successful deploy |

Typical order after a reset:

```
Reset Dev Environment → Porth — seed testbed tenants → E2E Tests
```

## Configuration

Set on the GitHub Environment named above, not at repo level unless stated.

**Variables**

| Name | Environment | Description |
|---|---|---|
| `AWS_ROLE_ARN` | all | OIDC role to assume in account `195950944420` |
| `AWS_CFN_EXECUTION_ROLE_ARN` | `porth-install` | Optional. CloudFormation execution role for the SAR install |
| `ACM_CERTIFICATE_ARN` | `sample-app-deploy` | Certificate for the CloudFront distribution (us-east-1) |
| `DNS_ZONE` | `porth-install` | e.g. `ems.estynsoftware.cloud` — drives the BFF cookie domain |
| `API_DOMAIN_NAME` | `porth-install` | Porth API custom domain FQDN |
| `PORTH_SPA_ORIGINS` | `porth-install` | CSV of allowed SPA origins |
| `PORTH_STACK_NAME` | `sample-app-deploy` | Defaults to `serverlessrepo-porth-components` |

**Secrets**

| Name | Environment | Description |
|---|---|---|
| `ACM_CERTIFICATE_ARN` | `porth-install` | Certificate for the Porth API custom domain (a `vars.` value of the same name is accepted as a legacy fallback) |
| `PORTH_AUTH_TEST_TOKEN` | `porth-install`, repo | Optional authorizer test-token bypass |
| Tier 2 e2e secrets | repo | `PLAYWRIGHT_BASE_URL`, `PORTH_PLATFORM_BASE_URL`, `PORTH_API_URL`, `PORTH_TENANT_CONFIG`, and the platform-admin / tenant-user email+password pairs |

> `PLATFORM_AUTH0_DOMAIN` / `_CLIENT_ID` / `_AUDIENCE` are **no longer read by any workflow** —
> the IdP config moved to SSM (below) and they can be deleted from the repo's secrets.

### Testbed configuration lives in AWS, not here

**This repository is public.** Actions logs are world-readable and GitHub masks only the
*exact* registered secret value — not one embedded in a JSON body, URL-encoded, or surfaced by
an error trace. Configuration held in repo variables is also unversioned and unaudited.

So everything the **bootstrap** needs lives in account `195950944420`, and the seed workflow's
only GitHub reference is `AWS_ROLE_ARN`.

**SSM Parameter Store**

| Parameter | | |
|---|---|---|
| `/porth/config/testbed` | in | The manifest: `platform` (its IdP config + admin identity) and `tenants` (each with its own `idp` block). Operator-authored — see `infra/qa-tools/testbed-manifest.example.json`. Read by the seed Lambda directly, so it never transits CI. String or SecureString both work |
| `/porth/testbed/tenants` | out | The **resolved** set the seeder publishes — org/role UUIDs plus each admin's email and secret name. The PORTH-494 config and Tier 2 are generated from this |
| `/porth/auth` | out | The BFF proxy's runtime config, written by `porth-install` from `platform.idp` merged with the stack outputs |

**Secrets Manager** — `porth/testbed/platform/password`, `porth/testbed/tenants/<id>/password`.
One per identity, referenced from the manifest by name. Create alongside the IdP user, which
needs that provider's management API:

```bash
aws secretsmanager create-secret --name porth/testbed/tenants/acme/password --secret-string '{"password":"…"}' --region us-east-1
```

The seeder only calls `DescribeSecret` — metadata, structurally incapable of returning a value.
Its IAM grants `DescribeSecret` and never `GetSecretValue`. The trailing `*` in that grant's
resource pattern is required: Secrets Manager appends a random suffix to every ARN.

**Install** configuration stays in the pipeline — the parameters above are the testbed's data
and identities, not the stack's shape.

Migrating the remaining Tier 2 password secrets to the same pattern is tracked in
[PORTH-533](https://estynsoftware.atlassian.net/browse/PORTH-533).

## Jira

This project is tracked under [PORTH-122](https://estynsoftware.atlassian.net/browse/PORTH-122).
