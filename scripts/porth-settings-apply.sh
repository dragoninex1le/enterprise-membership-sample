#!/usr/bin/env bash
# Write Porth's values into EMS's settings table (PORTH-669 ruling 3, Porth >= 0.4.30).
#
# The table and its empty key secret are EMS's (infra/terraform/ems-install-once,
# settings.tf). This runs `porth-install settings apply`: a dry run first (the
# plan is the audit trail), then --apply, which sets the table up on its first
# run and copies /porth/auth plus the values Porth used to hard-code into it.
#
# porth-install comes from the publisher's porth-py repository; its `settings`
# extra pulls estyn-settings from estyn-platform-py, so pip gets both indexes.
#
# Env: EFF_PORTH_VERSION, PORTH_INSTALL_VERSION, ESTYN_SETTINGS_TABLE,
#      ESTYN_SETTINGS_SECRET, CA_OWNER, AWS_REGION.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"

if ! "$here/porth-version-at-least.sh" 0.4.30 "${EFF_PORTH_VERSION:?}"; then
  echo "Porth ${EFF_PORTH_VERSION} predates the settings table; nothing to write."
  exit 0
fi

: "${PORTH_INSTALL_VERSION:?}" "${ESTYN_SETTINGS_TABLE:?}" "${ESTYN_SETTINGS_SECRET:?}"
: "${CA_OWNER:?}" "${AWS_REGION:?}"

index_for() {
  local domain="$1" repo="$2" token endpoint
  token=$(aws codeartifact get-authorization-token --domain "$domain" \
    --domain-owner "$CA_OWNER" --region "$AWS_REGION" \
    --query authorizationToken --output text)
  endpoint=$(aws codeartifact get-repository-endpoint --domain "$domain" \
    --domain-owner "$CA_OWNER" --repository "$repo" --format pypi \
    --region "$AWS_REGION" --query repositoryEndpoint --output text)
  echo "::add-mask::$token"
  printf 'https://aws:%s@%ssimple/' "$token" "${endpoint#https://}"
}

porth_index=$(index_for porth porth-py)
platform_index=$(index_for estyn-platform estyn-platform-py)

pip install --quiet \
  --index-url "$porth_index" \
  --extra-index-url "$platform_index" \
  "porth-install[settings]==${PORTH_INSTALL_VERSION}"
echo "porth-install $(pip show porth-install | awk '/^Version:/ {print $2}')," \
  "estyn-settings $(pip show estyn-settings | awk '/^Version:/ {print $2}')"

echo "── plan ──"
porth-install settings apply \
  --table "$ESTYN_SETTINGS_TABLE" --secret "$ESTYN_SETTINGS_SECRET"

echo "── apply ──"
porth-install settings apply \
  --table "$ESTYN_SETTINGS_TABLE" --secret "$ESTYN_SETTINGS_SECRET" --apply
