#!/usr/bin/env bash
# The deployed API answers (an empty login is refused before anything is signed or sent),
# and its URL goes in the run summary.
set -euo pipefail

STACK="enterprise-membership-sample-supplierlink-sim-$SLOT"
URL=$(aws cloudformation describe-stacks --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='SimulatorUrl'].OutputValue" --output text)

ANSWER=$(curl -s -X POST -H 'content-type: application/json' -d '{}' "${URL}login")
echo "${URL}login answered: $ANSWER"
if [ "$ANSWER" != '{"error": "tenant is required"}' ]; then
  echo "::error::the simulator API did not answer as expected"
  exit 1
fi

echo "## SupplierLink simulator API ($SLOT)" >> "$GITHUB_STEP_SUMMARY"
echo "" >> "$GITHUB_STEP_SUMMARY"
echo "API: $URL (the page is /supplierlink on the EMS frontend)" >> "$GITHUB_STEP_SUMMARY"
