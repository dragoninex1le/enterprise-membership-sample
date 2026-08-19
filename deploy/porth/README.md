# Porth deployment artefacts

Payloads the install pipeline writes, as files rather than as strings inside
`porth-install.yml`.

## Why they are here

They were inline. `porth-install.yml` carried three IAM policy documents, two
index maps and a Python program as quoted shell strings, and the escaping cost
real deploys:

- An apostrophe in a **comment** inside `python3 -c '...'` ended the shell string
  and broke the install. The error was a bash syntax error pointing at a
  parenthesis, nowhere near the comment (PORTH-589).
- A policy edit meant editing a 400-character single-quoted JSON line, where a
  wrong bracket is invisible in review and only fails at request time.
- Nothing could be linted, diffed or opened in an editor that understands JSON.

A file can be validated, diffed one key per line, and read without counting
quotes.

## What is here

| Path | Written to | Notes |
|---|---|---|
| `session-policy/tenant-scoped-default.json` | `/porth/{env}/auth-session-policy/tenant-scoped-default` | Narrows a tenant session. **Two** LeadingKeys patterns — see below |
| `session-policy/platform-scoped-default.json` | `…/platform-scoped-default` | Cross-tenant, never cross-environment. `Scan` sits alone and unconditioned on purpose |
| `session-policy/index.template.json` | `…/index` | Maps path prefixes and role keys to templates. Rendered with `{{ENV}}` |
| `auth-policy/allow-all.json` | `/porth/{env}/auth-policy/{name}` | The API-Gateway policy the authorizer returns |
| `auth-policy/index.json` | `/porth/{env}/auth-policy/index` | Route prefix → policy name |
| `scripts/build_auth_blob.py` | `/porth/auth` | Builds the OAuth-proxy config from the testbed manifest |
| `scripts/render.py` | — | Substitutes `{{PLACEHOLDER}}` tokens and validates the result |

## Two substitution syntaxes, and they are not interchangeable

| Syntax | Substituted by | When |
|---|---|---|
| `$env`, `$tenant` | the **authorizer**, per request | at request time |
| `{{ENV}}` | `scripts/render.py`, at deploy time | in the pipeline |

This is why `render.py` uses `{{…}}` rather than `$…`. A shell-style substitution
pass over these files would eat `$env` and `$tenant` and write a policy that
matches nothing — which fails closed, silently, and looks like a permissions
problem three layers away.

## The tenant policy needs both patterns

```json
"ENV#$env#TENANT#$tenant",
"ENV#$env#TENANT#$tenant#*"
```

A tenant record's partition key is exactly `ENV#{env}#TENANT#{tenant}` with **no
trailing separator**, so the `#*` pattern alone cannot match it — every tenant
route then fails in IAM at `Director.assert_readable()`, before any permission is
evaluated (PORTH-593).

Do **not** collapse them to `ENV#$env#TENANT#$tenant*`. Dropping the separator
makes it a prefix match, so tenant `acme` also reaches `acme-staging`. The outage
and its tempting one-character repair sit on opposite sides of the same edit,
which is why `porth-install check-session-policy` asserts both directions.

## Scope

These are the **consumer's** copy of Porth's seeding. Porth's own rules — the
origin policy keys, the permission catalogue — belong to `porth-install` and
travel with the release. Anything in this folder that turns out to be a Porth
rule rather than an EMS one should move there instead of being maintained twice.
