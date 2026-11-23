#!/usr/bin/env bash
# The deployed page answers, and its URL goes in the run summary.
set -euo pipefail

STACK="enterprise-membership-sample-supplierlink-sim-$SLOT"
URL=$(aws cloudformation describe-stacks --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='SimulatorUrl'].OutputValue" --output text)

STATUS=$(curl -s -o /dev/null -w '%{http_code}' "$URL")
echo "$URL answered $STATUS"
if [ "$STATUS" != "200" ]; then
  echo "::error::the simulator page did not answer 200"
  exit 1
fi

echo "## SupplierLink simulator ($SLOT)" >> "$GITHUB_STEP_SUMMARY"
echo "" >> "$GITHUB_STEP_SUMMARY"
echo "Open: $URL" >> "$GITHUB_STEP_SUMMARY"
