#!/usr/bin/env bash
# PORTH-656 — the Porth release this account is running: the porth-components
# stack's ImageTag parameter (which a release sets equal to its version).
#
# Usage: installed-porth-version.sh [stack-name]   (default serverlessrepo-porth-components)
set -euo pipefail
STACK="${1:-serverlessrepo-porth-components}"
VERSION=$(aws cloudformation describe-stacks --stack-name "$STACK" \
  --query "Stacks[0].Parameters[?ParameterKey=='ImageTag'].ParameterValue | [0]" \
  --output text)
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "::error::stack ${STACK} has no ImageTag version (got '${VERSION}')" >&2
  exit 1
fi
echo "$VERSION"
