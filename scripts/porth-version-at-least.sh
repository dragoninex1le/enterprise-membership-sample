#!/usr/bin/env bash
# Exit 0 when VERSION >= MINIMUM (dotted versions, e.g. 0.4.17), else 1.
#   scripts/porth-version-at-least.sh MINIMUM VERSION
set -euo pipefail
minimum="$1"
version="$2"
[ "$(printf '%s\n' "$minimum" "$version" | sort -V | head -1)" = "$minimum" ]
