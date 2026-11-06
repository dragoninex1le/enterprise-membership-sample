#!/usr/bin/env bash
# Print the Porth table names as KEY=value lines (for $GITHUB_ENV).
#
#   resolve-porth-tables.sh <porth-stack-name>
set -euo pipefail
STACK="${1:?porth stack name}"

out() {
  aws cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

for pair in TenantsTableName:PORTH_TENANTS_TABLE PermissionsTableName:PORTH_PERMISSIONS_TABLE \
            RolesTableName:PORTH_ROLES_TABLE ClaimMappingConfigsTableName:PORTH_CLAIM_MAPPING_CONFIGS_TABLE; do
  value=$(out "${pair%%:*}")
  if [ -z "$value" ] || [ "$value" = "None" ]; then
    echo "::error::$STACK has no ${pair%%:*} output" >&2
    exit 1
  fi
  echo "${pair#*:}=$value"
done
