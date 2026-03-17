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
cp .env.example .env.local   # fill in API URL and Auth0 config
npm run dev
```

## Deployment

```bash
sam deploy --guided
```

See [docs/deployment.md](docs/deployment.md) for the full walkthrough.

## GitHub Actions secrets required

| Secret | Description |
|--------|-------------|
| `AWS_DEPLOY_ROLE_ARN` | IAM role ARN for OIDC deploy |
| `PORTH_API_URL` | Base URL of the deployed Porth API |
| `VITE_AUTH0_DOMAIN` | Auth0 tenant domain |
| `VITE_AUTH0_CLIENT_ID` | Auth0 app client ID |
| `VITE_AUTH0_AUDIENCE` | Auth0 API audience |

## Jira

This project is tracked under [PORTH-122](https://estynsoftware.atlassian.net/browse/PORTH-122).
