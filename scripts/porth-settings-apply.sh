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

# Each token is masked before it is used. The ::add-mask:: line must reach the
# runner on the step's own stdout: printed inside a $(...) it is captured
# instead, the token goes unmasked and pip prints it in its warnings.
token_for() {
  aws codeartifact get-authorization-token --domain "$1" --domain-owner "$CA_OWNER" \
    --region "$AWS_REGION" --query authorizationToken --output text
}
endpoint_for() {
  aws codeartifact get-repository-endpoint --domain "$1" --domain-owner "$CA_OWNER" \
    --repository "$2" --format pypi --region "$AWS_REGION" --query repositoryEndpoint --output text
}

porth_token=$(token_for porth)
echo "::add-mask::$porth_token"
platform_token=$(token_for estyn-platform)
echo "::add-mask::$platform_token"

porth_endpoint=$(endpoint_for porth porth-py)
platform_endpoint=$(endpoint_for estyn-platform estyn-platform-py)

porth_index="https://aws:${porth_token}@${porth_endpoint#https://}simple/"
platform_index="https://aws:${platform_token}@${platform_endpoint#https://}simple/"

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
