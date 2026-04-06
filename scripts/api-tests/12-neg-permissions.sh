#!/usr/bin/env bash

# Porth API Negative Tests — Permissions
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

echo -e "${BLUE}=== Negative Tests: Permissions ===${NC}\n"

TENANT_ID="t-test-1"
APP_NAMESPACE="test-app"
RESPONSE_FILE="/tmp/porth-neg-permissions.json"

PAYLOAD=$(printf '{"tenant_id":"%s","app_namespace":"%s","permissions":[]}' "$TENANT_ID" "$APP_NAMESPACE")
STATUS=$(api_request "POST" "/permissions" "$RESPONSE_FILE" "$PAYLOAD" | tail -1)
if [[ "$STATUS" == "400" || "$STATUS" == "422" ]]; then pass "NEG-P01: empty permissions array (HTTP $STATUS)"
else fail "NEG-P01: empty array (expected 400/422, got $STATUS)"; fi

STATUS=$(api_request "GET" "/permissions/$TENANT_ID/$APP_NAMESPACE/nonexistent.key.xyz" "$RESPONSE_FILE" | tail -1)
if [[ "$STATUS" == "404" ]]; then pass "NEG-P05: nonexistent permission key (HTTP 404)"
else fail "NEG-P05: nonexistent key (expected 404, got $STATUS)"; fi

STATUS=$(api_request "POST" "/permissions" "$RESPONSE_FILE" '{}' | tail -1)
if [[ "$STATUS" == "400" || "$STATUS" == "422" ]]; then pass "NEG-P07: empty body (HTTP $STATUS)"
else fail "NEG-P07: empty body (expected 400/422, got $STATUS)"; fi

echo ""
echo -e "${BLUE}=== Permissions Negative Tests Summary ===${NC}"
echo -e "Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Failed: ${RED}$TESTS_FAILED${NC}"

exit $TESTS_FAILED
