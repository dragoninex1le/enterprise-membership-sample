#!/usr/bin/env bash
# PORTH-656 — run `porth-install check` against the declared environments.
#
#   CA_DOMAIN CA_REPO CA_OWNER        the porth-py CodeArtifact repository
#   PORTH_INSTALL_CHECK_VERSION       the release's porth-install, from its manifest
#   EFF_PORTH_VERSION                 the Porth release installed (limits the migrations checked)
#   PORTH_ENV_NAME                    the Porth stack's Environment (dev)
#   AUTH0_MGMT_CLIENT_ID/_SECRET      optional; enables the Auth0 checks
set -euo pipefail

aws codeartifact login --tool pip --domain "$CA_DOMAIN" --domain-owner "$CA_OWNER" \
  --repository "$CA_REPO" --region "$AWS_REGION"
: "${PORTH_INSTALL_CHECK_VERSION:?the install job did not output porth_install_version}"
pip install --quiet "porth-install==${PORTH_INSTALL_CHECK_VERSION}"

# The declared file, from main, exactly as the install read it.
git fetch --no-tags --depth=1 origin main:refs/remotes/origin/main
DECLARED="${RUNNER_TEMP:-/tmp}/environments.json"
if ! git show "origin/main:deploy/porth/environments.json" > "$DECLARED" 2>/dev/null; then
  echo "::warning::deploy/porth/environments.json is not on main yet — checking this branch's copy"
  cp deploy/porth/environments.json "$DECLARED"
fi

# The Auth0 domain is the issuer's host; the blob already names it.
if [ -n "${AUTH0_MGMT_CLIENT_ID:-}" ] && [ -n "${AUTH0_MGMT_CLIENT_SECRET:-}" ]; then
  ISSUER=$(aws ssm get-parameter --name /porth/auth --query Parameter.Value --output text \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("issuer",""))')
  AUTH0_DOMAIN=$(printf '%s' "$ISSUER" | sed -E 's#^https?://##; s#/.*$##')
  export AUTH0_DOMAIN
fi

# porth-install >= 0.4.7 reads the data tables itself (named from --branch) and
# WARNS about legacy rows; --target-version limits the key migrations it asks
# about to those this release carries. Older ones lack the flag.
EXTRA=()
if [ -n "${EFF_PORTH_VERSION:-}" ] && porth-install check --help | grep -q -- '--target-version'; then
  EXTRA=(--target-version "$EFF_PORTH_VERSION")
fi

porth-install check --environments-file "$DECLARED" --branch "${PORTH_ENV_NAME:-dev}" "${EXTRA[@]}"
