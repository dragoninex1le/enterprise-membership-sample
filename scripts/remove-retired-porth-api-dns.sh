#!/usr/bin/env bash
# PORTH-655 — delete the A-alias for the retired shared Porth API host.
#
# Exactly one record, by exact name, and only if it exists. Warn-don't-fail:
# an install must not fail over DNS hygiene.
#
# Usage: remove-retired-porth-api-dns.sh <host>   e.g. porth-api.ems.estynsoftware.cloud
set -uo pipefail

HOST="${1:-}"
HOST="${HOST%.}"
if [ -z "$HOST" ] || [ "${HOST#*.}" = "$HOST" ]; then
  echo "::warning::no retired host name given — nothing to remove"
  exit 0
fi
PARENT="${HOST#*.}"

HZ_ID=$(aws route53 list-hosted-zones-by-name --dns-name "${PARENT}." \
  --query "HostedZones[?Name=='${PARENT}.'].Id | [0]" --output text 2>/dev/null | sed 's|/hostedzone/||')
if [ -z "$HZ_ID" ] || [ "$HZ_ID" = "None" ]; then
  echo "::warning::no Route 53 zone for ${PARENT} — nothing to remove"
  exit 0
fi

RECORD=$(aws route53 list-resource-record-sets --hosted-zone-id "$HZ_ID" \
  --query "ResourceRecordSets[?Name=='${HOST}.' && Type=='A'] | [0]" --output json 2>/dev/null)
if [ -z "$RECORD" ] || [ "$RECORD" = "null" ]; then
  echo "✅ ${HOST}: no alias — already retired"
  exit 0
fi

BATCH=$(printf '{"Comment":"PORTH-655: retire the shared Porth API host","Changes":[{"Action":"DELETE","ResourceRecordSet":%s}]}' "$RECORD")
if aws route53 change-resource-record-sets --hosted-zone-id "$HZ_ID" --change-batch "$BATCH" >/dev/null; then
  echo "🗑️  ${HOST}: alias deleted"
else
  echo "::warning::could not delete the ${HOST} alias — delete it by hand in zone ${PARENT}"
fi
