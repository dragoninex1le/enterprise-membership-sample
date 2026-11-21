#!/usr/bin/env bash
# PRF-22 — enable the delegated-mint connectors EMS uses (ADR-Z12), in every
# declared environment, from deploy/porth/delegated/connectors.json.
#
# Install configuration, like the permissions: without it every mint for the
# connector is refused as connector_not_enabled. `put` converges, so a run on a
# configured environment rewrites the same row.
#
#   PORTH_INSTALL_VERSION   from the release manifest (resolve-porth-release.sh)
#   ENV_NAME                the Porth stack's Environment (table-name suffix)
#   ENV_SCOPES              JSON array of declared environments, e.g. ["porth-sample","porth-dau"]
#   CA_DOMAIN CA_REPO CA_OWNER AWS_REGION   (optional; defaults below)
set -euo pipefail

: "${PORTH_INSTALL_VERSION:?resolve-porth-release.sh did not set PORTH_INSTALL_VERSION}"
: "${ENV_NAME:?ENV_NAME is empty - cannot resolve the table name}"
: "${ENV_SCOPES:?ENV_SCOPES is empty - no declared environments}"

CONNECTORS_FILE="$(dirname "$0")/../deploy/porth/delegated/connectors.json"

aws codeartifact login --tool pip --domain "${CA_DOMAIN:-porth}" \
  --domain-owner "${CA_OWNER:-084847995635}" --repository "${CA_REPO:-porth-py}" \
  --region "${AWS_REGION:-us-east-1}"
pip install --quiet "porth-install==${PORTH_INSTALL_VERSION}"

SCOPES=$(printf '%s' "$ENV_SCOPES" | python3 -c 'import json,sys; print(" ".join(json.load(sys.stdin)))')
CONNECTORS=$(python3 "$(dirname "$0")/delegated_connectors.py" "$CONNECTORS_FILE")

for SCOPE in $SCOPES; do
  while IFS=' ' read -r CONNECTOR ROLES; do
    [ -n "$CONNECTOR" ] || continue
    echo "── ${SCOPE}: enable ${CONNECTOR} (allowed roles: ${ROLES}) ──"
    porth-install delegated-config put \
      --environment "$ENV_NAME" --slot "$SCOPE" \
      --connector "$CONNECTOR" --enable --allowed-roles "$ROLES" \
      --updated-by porth-install.yml --apply
  done <<< "$CONNECTORS"
done
