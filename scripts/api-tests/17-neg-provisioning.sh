#!/usr/bin/env bash

# Porth API Negative Tests — Provisioning
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

echo -e "${BLUE}=== Negative Tests: Provisioning ===${NC}\n"

TENANT_ID="t-test-1"
RESPONSE_FILE="/tmp/porth-neg-provisioning.json"
ORG_ID=$(python3 -c "import json; data = json.load(open('/tmp/porth-test-setup-ids.json')); print(data.get('org_id', ''))" 2>/dev/null || echo "")

PAYLOAD=$(printf '{"organization_id":"%s","tenant_id":"%s","email":"neg@test.com","jwt_claims":{"sub":"ext"}}' "$ORG_ID" "$TENANT_ID")
STATUS=$(api_request "POST" "/users/provision" "$RESPONSE_FILE" "$PAYLOAD" | tail -1)
if [[ "$STATUS" == "400" || "$STATUS" == "422" ]]; then pass "NEG-PR01: missing external_id (HTTP $STATUS)"
else fail "NEG-PR01: missing external_id (expected 400/422, got $STATUS)"; fi

PAYLOAD=$(printf '{"external_id":"ext","organization_id":"%s","email":"neg@test.com","jwt_claims":{"sub":"ext"}}' "$ORG_ID")
STATUS=$(api_request "POST" "/users/provision" "$RESPONSE_FILE" "$PAYLOAD" | tail -1)
if [[ "$STATUS" == "400" || "$STATUS" == "422" ]]; then pass "NEG-PR02: missing tenant_id (HTTP $STATUS)"
else fail "NEG-PR02: missing tenant_id (expected 400/422, got $STATUS)"; fi

PAYLOAD=$(printf '{"external_id":"ext","organization_id":"%s","tenant_id":"nonexistent-xyz","email":"neg@test.com","jwt_claims":{"sub":"ext"}}' "$ORG_ID")
STATUS=$(api_request "POST" "/users/provision" "$RESPONSE_FILE" "$PAYLOAD" | tail -1)
if [[ "$STATUS" == "404" || "$STATUS" == "403" ]]; then pass "NEG-PR05: nonexistent tenant (HTTP $STATUS)"
else fail "NEG-PR05: nonexistent tenant (expected 404/403, got $STATUS)"; fi

STATUS=$(api_request "POST" "/users/provision" "$RESPONSE_FILE" '{}' | tail -1)
if [[ "$STATUS" == "400" || "$STATUS" == "422" ]]; then pass "NEG-PR07: empty body (HTTP $STATUS)"
else fail "NEG-PR07: empty body (expected 400/422, got $STATUS)"; fi

echo ""
echo -e "${BLUE}=== Provisioning Negative Tests Summary ===${NC}"
echo -e "Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Failed: ${RED}$TESTS_FAILED${NC}"

exit $TESTS_FAILED
