#!/usr/bin/env bash

# Porth API Negative Tests — Organizations
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

echo -e "${BLUE}=== Negative Tests: Organizations ===${NC}\n"

RESPONSE_FILE="/tmp/porth-neg-orgs.json"

PAYLOAD='{"slug": "neg-test-no-name", "tenant": {"tenant_id": "t-neg-o01", "display_name": "Neg Test", "environment_type": "development"}}'
STATUS=$(api_request "POST" "/organizations" "$RESPONSE_FILE" "$PAYLOAD" | tail -1)
if [[ "$STATUS" == "400" || "$STATUS" == "422" ]]; then pass "NEG-O01: missing name (HTTP $STATUS)"
else fail "NEG-O01: missing name (expected 400/422, got $STATUS)"; fi

PAYLOAD='{"name": "Neg Test No Slug", "tenant": {"tenant_id": "t-neg-o02", "display_name": "Neg Test", "environment_type": "development"}}'
STATUS=$(api_request "POST" "/organizations" "$RESPONSE_FILE" "$PAYLOAD" | tail -1)
if [[ "$STATUS" == "400" || "$STATUS" == "422" ]]; then pass "NEG-O02: missing slug (HTTP $STATUS)"
else fail "NEG-O02: missing slug (expected 400/422, got $STATUS)"; fi

PAYLOAD='{"name": "Neg Test No Tenant", "slug": "neg-test-no-tenant"}'
STATUS=$(api_request "POST" "/organizations" "$RESPONSE_FILE" "$PAYLOAD" | tail -1)
if [[ "$STATUS" == "400" || "$STATUS" == "422" ]]; then pass "NEG-O03: missing tenant (HTTP $STATUS)"
else fail "NEG-O03: missing tenant (expected 400/422, got $STATUS)"; fi

PAYLOAD='{"name": "Dup Slug Org", "slug": "test-org-smoke", "tenant": {"tenant_id": "t-neg-o04", "display_name": "Dup", "environment_type": "development"}}'
STATUS=$(api_request "POST" "/organizations" "$RESPONSE_FILE" "$PAYLOAD" | tail -1)
if [[ "$STATUS" == "409" || "$STATUS" == "400" ]]; then pass "NEG-O04: duplicate slug (HTTP $STATUS)"
else fail "NEG-O04: duplicate slug (expected 409/400, got $STATUS)"; fi

STATUS=$(api_request "GET" "/organizations/nonexistent-org-id-xyz" "$RESPONSE_FILE" | tail -1)
if [[ "$STATUS" == "404" ]]; then pass "NEG-O05: GET nonexistent org (HTTP 404)"
else fail "NEG-O05: GET nonexistent org (expected 404, got $STATUS)"; fi

STATUS=$(api_request "GET" "/organizations/slug/nonexistent-slug-xyz" "$RESPONSE_FILE" | tail -1)
if [[ "$STATUS" == "404" ]]; then pass "NEG-O06: GET nonexistent slug (HTTP 404)"
else fail "NEG-O06: GET nonexistent slug (expected 404, got $STATUS)"; fi

STATUS=$(api_request "PATCH" "/organizations/nonexistent-org-id-xyz" "$RESPONSE_FILE" '{"name": "Updated"}' | tail -1)
if [[ "$STATUS" == "404" ]]; then pass "NEG-O07: PATCH nonexistent org (HTTP 404)"
else fail "NEG-O07: PATCH nonexistent org (expected 404, got $STATUS)"; fi

STATUS=$(api_request "POST" "/organizations" "$RESPONSE_FILE" '{}' | tail -1)
if [[ "$STATUS" == "400" || "$STATUS" == "422" ]]; then pass "NEG-O08: empty body (HTTP $STATUS)"
else fail "NEG-O08: empty body (expected 400/422, got $STATUS)"; fi

echo ""
echo -e "${BLUE}=== Organizations Negative Tests Summary ===${NC}"
echo -e "Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Failed: ${RED}$TESTS_FAILED${NC}"

exit $TESTS_FAILED
