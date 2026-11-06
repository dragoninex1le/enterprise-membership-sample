#!/usr/bin/env bash
# PORTH-656 — alias records for a tenant-API-host slot.
#
#   upsert-tenant-api-dns.sh <stack-name> <dns-root>
#
#   *.api.{slot}.{zone}  -> the stack's TenantApiDomain   (regional target)
#   api.{slot}.{zone}    -> the stack's PlatformApiDomain (regional target)
#
# Not stack resources for the reason SampleAppApiDomain's record is not: a
# RecordSet with HostedZoneName needs route53:ListHostedZones, and the deploy
# role holds ListHostedZonesByName. Both records go in one change batch so they
# move together.
#
# api.{slot}.{zone} is an exact record, so it wins over the *.{slot}.{zone}
# wildcard that points at CloudFront; *.api.{slot}.{zone} is the closer wildcard
# for every {tenant}.api.{slot}.{zone}.
set -euo pipefail

STACK="${1:?stack name}"
DNS_ROOT="${2:?dns root, e.g. ems.estynsoftware.cloud.}"

output() {
  aws cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

APEX=$(aws cloudformation describe-stacks --stack-name "$STACK" \
  --query "Stacks[0].Parameters[?ParameterKey=='CloudFrontApexAlias'].ParameterValue" --output text)
TENANT_TARGET=$(output TenantApiRegionalDomainName)
TENANT_ZONE=$(output TenantApiRegionalHostedZoneId)
PLATFORM_TARGET=$(output PlatformApiRegionalDomainName)
PLATFORM_ZONE=$(output PlatformApiRegionalHostedZoneId)

for v in APEX TENANT_TARGET TENANT_ZONE PLATFORM_TARGET PLATFORM_ZONE; do
  if [ -z "${!v}" ] || [ "${!v}" = "None" ]; then
    echo "::error::$v did not resolve from stack $STACK. Is TenantApiHosts 'true' on this slot?"
    exit 1
  fi
done

HOSTED_ZONE_ID=$(aws route53 list-hosted-zones-by-name --dns-name "$DNS_ROOT" \
  --query "HostedZones[0].Id" --output text | sed 's|/hostedzone/||')

BATCH=$(jq -n \
  --arg tname "*.api.${APEX}" --arg ttarget "$TENANT_TARGET" --arg tzone "$TENANT_ZONE" \
  --arg pname "api.${APEX}" --arg ptarget "$PLATFORM_TARGET" --arg pzone "$PLATFORM_ZONE" \
  '{Changes: [
     {Action: "UPSERT", ResourceRecordSet: {Name: $tname, Type: "A",
       AliasTarget: {HostedZoneId: $tzone, DNSName: $ttarget, EvaluateTargetHealth: false}}},
     {Action: "UPSERT", ResourceRecordSet: {Name: $pname, Type: "A",
       AliasTarget: {HostedZoneId: $pzone, DNSName: $ptarget, EvaluateTargetHealth: false}}}
   ]}')

echo "Upserting (HZ $HOSTED_ZONE_ID):"
echo "  *.api.${APEX} -> ${TENANT_TARGET}"
echo "  api.${APEX}   -> ${PLATFORM_TARGET}"
aws route53 change-resource-record-sets --hosted-zone-id "$HOSTED_ZONE_ID" --change-batch "$BATCH" >/dev/null
echo "✅ tenant API host aliases upserted"
