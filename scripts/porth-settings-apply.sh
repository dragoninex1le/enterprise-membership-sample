#!/usr/bin/env bash
# Write Porth's values into EMS's settings table (PORTH-669 ruling 3, Porth >= 0.4.30).
#
# The table and its empty key secret are EMS's (infra/terraform/ems-install-once,
# settings.tf). This runs `porth-install settings apply`: a dry run first (the
# plan is the audit trail), then --apply, which sets the table up on its first
# run and copies /porth/auth plus the values Porth used to hard-code into it.
#
# Runs twice from Porth 0.4.31: before the stack update (0.4.31 reads items
# 0.4.30's install never wrote) and after auth-config; the second is a no-op.
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

"$here/porth-install-pip.sh" "$PORTH_INSTALL_VERSION"

echo "── plan ──"
porth-install settings apply \
  --table "$ESTYN_SETTINGS_TABLE" --secret "$ESTYN_SETTINGS_SECRET"

echo "── apply ──"
porth-install settings apply \
  --table "$ESTYN_SETTINGS_TABLE" --secret "$ESTYN_SETTINGS_SECRET" --apply
