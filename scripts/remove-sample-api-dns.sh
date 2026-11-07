#!/usr/bin/env bash
# PORTH-656 — remove the sample-api.{slot} alias from a tenant-API-host slot.
#
#   remove-sample-api-dns.sh <record-name> <dns-root>
#
# On a tenant-API-host slot the stack no longer creates the sample-api.{slot}
# domain (CloudFront has no /sample/* behaviour; the SPA calls
# {tenant}.api.{slot}/sample). The alias deploy-sample-app.yml upserted for it
# then points at nothing, so it is removed — this one record, by exact name.
#
# Route 53 deletes only an exact match, so the record is read first. Absent:
# nothing to do. Any failure is a warning, not a failed deploy: a leftover
# alias is untidy, not broken.
set -euo pipefail

NAME="${1:?record name, e.g. sample-api.porth-dau.ems.estynsoftware.cloud}"
DNS_ROOT="${2:?dns root, e.g. ems.estynsoftware.cloud.}"
FQDN="${NAME%.}."

ZONE_ID=$(aws route53 list-hosted-zones-by-name --dns-name "$DNS_ROOT" \
  --query "HostedZones[0].Id" --output text | sed 's|/hostedzone/||')

if ! RECORD=$(aws route53 list-resource-record-sets --hosted-zone-id "$ZONE_ID" \
      --start-record-name "$FQDN" --start-record-type A --max-items 1 \
      --query "ResourceRecordSets[?Name=='$FQDN' && Type=='A'] | [0]" --output json 2>&1); then
  echo "::warning::could not read $FQDN from Route 53 — leaving it: $RECORD"
  exit 0
fi

if [ -z "$RECORD" ] || [ "$RECORD" = "null" ]; then
  echo "✅ $FQDN is already gone"
  exit 0
fi

BATCH=$(jq -n --argjson rr "$RECORD" '{Changes: [{Action: "DELETE", ResourceRecordSet: $rr}]}')
if aws route53 change-resource-record-sets --hosted-zone-id "$ZONE_ID" \
     --change-batch "$BATCH" >/dev/null 2>"${RUNNER_TEMP:-/tmp}/r53.err"; then
  echo "✅ removed $FQDN (this slot serves its API on the tenant API hosts)"
else
  echo "::warning::could not remove $FQDN — $(cat "${RUNNER_TEMP:-/tmp}/r53.err")"
fi
