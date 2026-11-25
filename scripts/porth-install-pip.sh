#!/usr/bin/env bash
# Install porth-install with its `settings` extra (PORTH-669).
#
#   scripts/porth-install-pip.sh <version>
#
# From porth-install 0.4.21 (Porth 0.4.31), reconcile-permissions, check,
# tenants apply and platform-marker read Porth's settings from EMS's settings
# table, so they need estyn-settings, which lives in estyn-platform-py. pip
# gets both CodeArtifact indexes.
#
# Each token is masked before it is used. The ::add-mask:: line must reach the
# runner on the step's own stdout: printed inside a $(...) it is captured
# instead, the token goes unmasked and pip prints it in its warnings.
#
# Env: CA_OWNER (default 084847995635), AWS_REGION (default us-east-1).
set -euo pipefail

version="${1:?usage: porth-install-pip.sh <porth-install version>}"
owner="${CA_OWNER:-084847995635}"
region="${AWS_REGION:-us-east-1}"

token_for() {
  aws codeartifact get-authorization-token --domain "$1" --domain-owner "$owner" \
    --region "$region" --query authorizationToken --output text
}
endpoint_for() {
  aws codeartifact get-repository-endpoint --domain "$1" --domain-owner "$owner" \
    --repository "$2" --format pypi --region "$region" --query repositoryEndpoint --output text
}

porth_token=$(token_for porth)
echo "::add-mask::$porth_token"
platform_token=$(token_for estyn-platform)
echo "::add-mask::$platform_token"

porth_endpoint=$(endpoint_for porth porth-py)
platform_endpoint=$(endpoint_for estyn-platform estyn-platform-py)

pip install --quiet \
  --index-url "https://aws:${porth_token}@${porth_endpoint#https://}simple/" \
  --extra-index-url "https://aws:${platform_token}@${platform_endpoint#https://}simple/" \
  "porth-install[settings]==${version}"
echo "porth-install $(pip show porth-install | awk '/^Version:/ {print $2}')," \
  "estyn-settings $(pip show estyn-settings 2>/dev/null | awk '/^Version:/ {print $2}')"
