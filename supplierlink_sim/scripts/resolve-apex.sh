#!/usr/bin/env bash
# EMS's API apex for $SLOT (e.g. porth-dau.ems.estynsoftware.cloud), read from the EMS
# stack's CloudFrontApexAlias parameter. Writes API_APEX to $GITHUB_ENV.
set -euo pipefail

if [ "$SLOT" = "porth-sample" ]; then
  EMS_STACK=enterprise-membership-sample
else
  EMS_STACK="enterprise-membership-sample-$SLOT"
fi

APEX=$(aws cloudformation describe-stacks --stack-name "$EMS_STACK" \
  --query "Stacks[0].Parameters[?ParameterKey=='CloudFrontApexAlias'].ParameterValue" --output text)

if [ -z "$APEX" ] || [ "$APEX" = "None" ]; then
  echo "::error::$EMS_STACK has no CloudFrontApexAlias - is EMS deployed on $SLOT?"
  exit 1
fi

echo "EMS stack $EMS_STACK, API apex $APEX"
echo "API_APEX=$APEX" >> "$GITHUB_ENV"
