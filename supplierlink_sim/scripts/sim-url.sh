#!/usr/bin/env bash
# For the EMS frontend build (deploy-sample-app.yml): the SupplierLink simulator API's URL
# on $ENVIRONMENT_SLOT, read from its stack. Writes SUPPLIERLINK_SIM_URL to $GITHUB_ENV.
# Not deployed on the slot yet: empty, and the /supplierlink page says so.
set -euo pipefail

STACK="enterprise-membership-sample-supplierlink-sim-$ENVIRONMENT_SLOT"
URL=$(aws cloudformation describe-stacks --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='SimulatorUrl'].OutputValue" --output text 2>/dev/null || true)

if [ -z "$URL" ] || [ "$URL" = "None" ]; then
  echo "::warning::$STACK not found - /supplierlink will have no simulator API (run deploy-supplierlink-sim.yml)"
  URL=""
fi

echo "SupplierLink simulator API: ${URL:-none}"
echo "SUPPLIERLINK_SIM_URL=$URL" >> "$GITHUB_ENV"
