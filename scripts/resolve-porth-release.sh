#!/usr/bin/env bash
# PORTH-657 — resolve a Porth release version to the template URL to install from.
#
# Reads s3://$PORTH_RELEASE_BUCKET/porth/<version>/manifest.json (written last by the
# Components "Porth release" workflow, so its presence means the version is released),
# checks it describes the version asked for, and writes `template_url` and
# `porth_install_version` to $GITHUB_OUTPUT (and PORTH_INSTALL_VERSION to $GITHUB_ENV).
#
# PORTH-656: the porth-install this install runs is the one the release was cut
# with (manifest components["porth-install"]), not a pin in this repo. A pin kept
# EMS on porth-install 0.3.0 for the install steps and 0.4.4 for `check` while
# Porth shipped 0.4.11, so every migration and check added since never ran here.
# The manifest's version is exact, so pip cannot backtrack to an older one (the
# reason the pin existed).
#
# Usage: resolve-porth-release.sh <version>
# Env:   PORTH_RELEASE_BUCKET (default porth-releases-084847995635), AWS_REGION
set -euo pipefail

VERSION="${1:?usage: resolve-porth-release.sh <version>}"
BUCKET="${PORTH_RELEASE_BUCKET:-porth-releases-084847995635}"
REGION="${AWS_REGION:-us-east-1}"
KEY="porth/${VERSION}/manifest.json"
MANIFEST="$(mktemp)"
trap 'rm -f "$MANIFEST"' EXIT

if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "::error::porth_version '$VERSION' is not MAJOR.MINOR.PATCH"
  exit 1
fi

if ! ERR="$(aws s3 cp "s3://${BUCKET}/${KEY}" "$MANIFEST" --region "$REGION" --only-show-errors 2>&1)"; then
  echo "::error::Could not read s3://${BUCKET}/${KEY}: ${ERR}"
  echo "::error::Either Porth ${VERSION} has not been released (no manifest), or this role lacks s3:GetObject on arn:aws:s3:::${BUCKET}/porth/*. Ask the Porth team which."
  exit 1
fi

read -r M_VERSION TEMPLATE_URL IMAGE GIT_SHA PORTH_INSTALL < <(python3 - "$MANIFEST" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
print(m["version"], m["template_url"], m["image"], m["git_sha"],
      (m.get("components") or {}).get("porth-install") or "-")
PY
)

if [ "$M_VERSION" != "$VERSION" ]; then
  echo "::error::Manifest at ${KEY} says version ${M_VERSION}, not ${VERSION}. Refusing to install."
  exit 1
fi
case "$TEMPLATE_URL" in
  "https://${BUCKET}.s3.${REGION}.amazonaws.com/porth/${VERSION}/template.yaml") ;;
  *) echo "::error::Manifest template_url ${TEMPLATE_URL} is not this release's template. Refusing to install."; exit 1 ;;
esac

if [[ ! "$PORTH_INSTALL" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "::error::Manifest at ${KEY} names no porth-install version (components[\"porth-install\"]). Refusing to guess one."
  exit 1
fi

echo "✅ Porth ${VERSION}: ${TEMPLATE_URL}"
echo "   porth-install ${PORTH_INSTALL} (from the release manifest)"
echo "   image ${IMAGE}, Components commit ${GIT_SHA}"
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  echo "template_url=${TEMPLATE_URL}" >> "$GITHUB_OUTPUT"
  echo "porth_install_version=${PORTH_INSTALL}" >> "$GITHUB_OUTPUT"
fi
if [ -n "${GITHUB_ENV:-}" ]; then
  echo "PORTH_INSTALL_VERSION=${PORTH_INSTALL}" >> "$GITHUB_ENV"
fi
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    echo "- **Porth release:** ${VERSION} (\`${TEMPLATE_URL}\`)"
    echo "- **Image:** \`${IMAGE}\`"
    echo "- **porth-install:** ${PORTH_INSTALL} (from the release manifest)"
    echo "- **Components commit:** \`${GIT_SHA}\`"
  } >> "$GITHUB_STEP_SUMMARY"
fi
