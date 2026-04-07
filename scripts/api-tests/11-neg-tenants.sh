#!/usr/bin/env bash

# Porth API Negative Tests — Tenants
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

echo -e "${BLUE}=== Negative Tests: Tenants ===${NC}\n"

RESPONSE_FILE="/tmp/porth-neg-tenants.json"
TENANT_ID="t-test-1"
ORG_ID=$(python3 -c "import json; data = json.load(open('/tmp/porth-test-setup-ids.json')); print(data.get('org_id', ''))" 2>/dev/null || echo "")

STATUS=$(api_request "PUT" "/tenants" "$RESPONSE_FILE" '{"org_id": "nonexistent-org-xyz", "tenant_id": "t-neg-t01", "display_name": "Neg Test", "environment_type": "development"}' | tail -1)
if [[ "$STATUS" == "404" ]]; then pass "NEG-T01: PUT nonexistent org_id (HTTP 404)"
else fail "NEG-T01: PUT nonexistent org_id (expected 404, got $STATUS)"; fi

echo "NEG-T02: PUT duplicate tenant_id '$TENANT_ID'"
if [[ -n "$ORG_ID" ]]; then
    PAYLOAD=$(cat <<EOF
{"org_id": "$ORG_ID", "tenant_id": "$TENANT_ID", "display_name": "Duplicate", "environment_type": "development"}
EOF
)
    STATUS=$(api_request "PUT" "/tenants" "$RESPONSE_FILE" "$PAYLOAD" | tail -1)
    if [[ "$STATUS" == "409" || "$STATUS" == "400" ]]; then pass "NEG-T02: duplicate tenant_id (HTTP $STATUS)"
    else fail "NEG-T02: duplicate tenant_id (expected 409/400, got $STATUS)"; fi
else
    fail "NEG-T02: Skipped — org_id not available from setup"
fi

STATUS=$(api_request "PUT" "/tenants" "$RESPONSE_FILE" '{"org_id": "some-org", "display_name": "No TenantID", "environment_type": "development"}' | tail -1)
if [[ "$STATUS" == "400" || "$STATUS" == "422" ]]; then pass "NEG-T03: missing tenant_id (HTTP $STATUS)"
else fail "NEG-T03: missing tenant_id (expected 400/422, got $STATUS)"; fi

STATUS=$(api_request "GET" "/tenants/nonexistent-tenant-xyz" "$RESPONSE_FILE" | tail -1)
if [[ "$STATUS" == "404" ]]; then pass "NEG-T04: GET nonexistent tenant (HTTP 404)"
else fail "NEG-T04: GET nonexistent tenant (expected 404, got $STATUS)"; fi

STATUS=$(api_request "PATCH" "/tenants/nonexistent-tenant-xyz" "$RESPONSE_FILE" '{"display_name": "Updated"}' | tail -1)
if [[ "$STATUS" == "404" ]]; then pass "NEG-T05: PATCH nonexistent tenant (HTTP 404)"
else fail "NEG-T05: PATCH nonexistent tenant (expected 404, got $STATUS)"; fi

STATUS=$(api_request "POST" "/tenants/nonexistent-tenant-xyz/suspend" "$RESPONSE_FILE" "" | tail -1)
if [[ "$STATUS" == "404" ]]; then pass "NEG-T06: suspend nonexistent (HTTP 404)"
else fail "NEG-T06: suspend nonexistent (expected 404, got $STATUS)"; fi

STATUS=$(api_request "POST" "/tenants/nonexistent-tenant-xyz/reactivate" "$RESPONSE_FILE" "" | tail -1)
if [[ "$STATUS" == "404" ]]; then pass "NEG-T07: reactivate nonexistent (HTTP 404)"
else fail "NEG-T07: reactivate nonexistent (expected 404, got $STATUS)"; fi

STATUS=$(api_request "POST" "/tenants/nonexistent-tenant-xyz/decommission" "$RESPONSE_FILE" "" | tail -1)
if [[ "$STATUS" == "404" ]]; then pass "NEG-T08: decommission nonexistent (HTTP 404)"
else fail "NEG-T08: decommission nonexistent (expected 404, got $STATUS)"; fi

echo "NEG-T09: double suspend"
api_request "POST" "/tenants/$TENANT_ID/suspend" "$RESPONSE_FILE" "" | tail -1 > /dev/null 2>&1 || true
STATUS=$(api_request "POST" "/tenants/$TENANT_ID/suspend" "$RESPONSE_FILE" "" | tail -1)
if [[ "$STATUS" == "409" ]]; then pass "NEG-T09: double suspend (HTTP 409)"
else fail "NEG-T09: double suspend (expected 409, got $STATUS)"; fi

echo "NEG-T10: double decommission"
api_request "POST" "/tenants/$TENANT_ID/reactivate" "$RESPONSE_FILE" "" | tail -1 > /dev/null 2>&1 || true
api_request "POST" "/tenants/$TENANT_ID/decommission" "$RESPONSE_FILE" "" | tail -1 > /dev/null 2>&1 || true
STATUS=$(api_request "POST" "/tenants/$TENANT_ID/decommission" "$RESPONSE_FILE" "" | tail -1)
if [[ "$STATUS" == "409" ]]; then pass "NEG-T10: double decommission (HTTP 409)"
else fail "NEG-T10: double decommission (expected 409, got $STATUS)"; fi

echo -e "${YELLOW}Cleanup: reactivating $TENANT_ID${NC}"
CLEANUP_STATUS=$(api_request "POST" "/tenants/$TENANT_ID/reactivate" "$RESPONSE_FILE" "" | tail -1)
if [[ "$CLEANUP_STATUS" != "200" ]]; then
    VERIFY_STATUS=$(api_request "GET" "/tenants/$TENANT_ID" "$RESPONSE_FILE" | tail -1)
    TENANT_STATE=$(python3 -c "import json; d=json.load(open('$RESPONSE_FILE')); print(d.get('status',''))" 2>/dev/null || echo "")
    if [[ "$TENANT_STATE" != "active" ]]; then
        fail "Cleanup: failed to reactivate $TENANT_ID"
    fi
fi

STATUS=$(api_request "PUT" "/tenants" "$RESPONSE_FILE" '{}' | tail -1)
if [[ "$STATUS" == "400" || "$STATUS" == "422" ]]; then pass "NEG-T11: empty body (HTTP $STATUS)"
else fail "NEG-T11: empty body (expected 400/422, got $STATUS)"; fi

STATUS=$(api_request "GET" "/tenants/organization/nonexistent-org-xyz" "$RESPONSE_FILE" | tail -1)
if [[ "$STATUS" == "404" ]]; then pass "NEG-T12: list tenants nonexistent org (HTTP 404)"
else fail "NEG-T12: list tenants nonexistent org (expected 404, got $STATUS)"; fi

echo ""
echo -e "${BLUE}=== Tenants Negative Tests Summary ===${NC}"
echo -e "Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Failed: ${RED}$TESTS_FAILED${NC}"

exit $TESTS_FAILED
