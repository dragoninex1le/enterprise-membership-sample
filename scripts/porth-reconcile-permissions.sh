#!/usr/bin/env bash
# PORTH-656 — make each declared environment's Porth permissions match the
# release being installed, and list (or, with PRUNE=true, remove) the ones
# Porth no longer ships.
#
#   PORTH_INSTALL_VERSION   from the release manifest (resolve-porth-release.sh)
#   ENV_NAME                the Porth stack's Environment (table-name suffix)
#   ENV_SCOPES              JSON array of declared environments, e.g. ["porth-sample","porth-dau"]
#   PRUNE                   "true" to delete retired permissions and their grants
#   CA_DOMAIN CA_REPO CA_OWNER AWS_REGION   (optional; defaults below)
set -euo pipefail

: "${PORTH_INSTALL_VERSION:?resolve-porth-release.sh did not set PORTH_INSTALL_VERSION}"
: "${ENV_NAME:?ENV_NAME is empty — cannot resolve the table names}"
: "${ENV_SCOPES:?ENV_SCOPES is empty — no declared environments}"

aws codeartifact login --tool pip --domain "${CA_DOMAIN:-porth}" \
  --domain-owner "${CA_OWNER:-084847995635}" --repository "${CA_REPO:-porth-py}" \
  --region "${AWS_REGION:-us-east-1}"
pip install --quiet "porth-install==${PORTH_INSTALL_VERSION}"

HAS_PRUNE=false
porth-install reconcile-permissions --help | grep -q -- '--prune-retired' && HAS_PRUNE=true

for SCOPE in $(printf '%s' "$ENV_SCOPES" | python3 -c 'import json,sys; print(" ".join(json.load(sys.stdin)))'); do
  COMMON=(
    --permissions-table "porth-permissions-${ENV_NAME}"
    --roles-table "porth-roles-${ENV_NAME}"
    --tenants-table "porth-tenants-${ENV_NAME}"
    --environment "$SCOPE"
    --tenants all
  )
  echo "── ${SCOPE}: reconcile ──"
  # Registers what this release ships and grants it to the admin roles. Writes;
  # converges, so a reconciled environment is a read that changes nothing.
  porth-install reconcile-permissions "${COMMON[@]}"

  # --prune-retired arrived in porth-install 0.4.6. Separate call: with it, the
  # whole run is a dry run unless --apply, and the reconcile above must apply.
  if [ "$HAS_PRUNE" = true ]; then
    if [ "${PRUNE:-false}" = "true" ]; then
      echo "── ${SCOPE}: prune retired permissions (APPLY) ──"
      echo "::warning::prune_retired is on — ${SCOPE}: retired Porth permissions and every grant to them are being DELETED"
      porth-install reconcile-permissions "${COMMON[@]}" --prune-retired --apply
    else
      echo "── ${SCOPE}: retired permissions (dry run — re-run with prune_retired to remove) ──"
      porth-install reconcile-permissions "${COMMON[@]}" --prune-retired
    fi
  fi
done
