#!/usr/bin/env bash

# Porth API Negative Tests — Users
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

echo -e "${BLUE}=== Negative Tests: Users ===${NC}\n"

TENANT_ID="t-test-1"
RESPONSE_FILE="/tmp/porth-neg-users.json"
USER_FILE="/tmp/porth-test-user-id.json"
USER_ID=$(python3 -c "import json; data = json.load(open('$USER_FILE')); print(data.get('user_id', ''))" 2>/dev/null || echo "")
ORG_ID=$(python3 -c "import json; data = json.load(open('/tmp/porth-test-setup-ids.json')); print(data.get('org_id', ''))" 2>/dev/null || echo "")

STATUS=$(api_request "GET" "/users/nonexistent-user-id-xyz" "$RESPONSE_FILE" | tail -1)
if [[ "$STATUS" == "404" ]]; then pass "NEG-U01: GET nonexistent user (HTTP 404)"
else fail "NEG-U01: GET nonexistent user (expected 404, got $STATUS)"; fi

STATUS=$(api_request "PATCH" "/users/nonexistent-user-id-xyz" "$RESPONSE_FILE" '{"display_name": "Updated"}' | tail -1)
if [[ "$STATUS" == "404" ]]; then pass "NEG-U02: PATCH nonexistent user (HTTP 404)"
else fail "NEG-U02: PATCH nonexistent user (expected 404, got $STATUS)"; fi

STATUS=$(api_request "POST" "/users/nonexistent-user-id-xyz/suspend" "$RESPONSE_FILE" "" | tail -1)
if [[ "$STATUS" == "404" ]]; then pass "NEG-U06: suspend nonexistent user (HTTP 404)"
else fail "NEG-U06: suspend nonexistent (expected 404, got $STATUS)"; fi

STATUS=$(api_request "POST" "/users/nonexistent-user-id-xyz/reactivate" "$RESPONSE_FILE" "" | tail -1)
if [[ "$STATUS" == "404" ]]; then pass "NEG-U07: reactivate nonexistent user (HTTP 404)"
else fail "NEG-U07: reactivate nonexistent (expected 404, got $STATUS)"; fi

if [[ -n "$USER_ID" ]]; then
    api_request "POST" "/users/$USER_ID/suspend" "$RESPONSE_FILE" "" | tail -1 > /dev/null 2>&1 || true
    STATUS=$(api_request "POST" "/users/$USER_ID/suspend" "$RESPONSE_FILE" "" | tail -1)
    if [[ "$STATUS" == "409" ]]; then pass "NEG-U12: double suspend (HTTP 409)"
    else fail "NEG-U12: double suspend (expected 409, got $STATUS)"; fi
    api_request "POST" "/users/$USER_ID/reactivate" "$RESPONSE_FILE" "" | tail -1 > /dev/null 2>&1 || true
fi

echo ""
echo -e "${BLUE}=== Users Negative Tests Summary ===${NC}"
echo -e "Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Failed: ${RED}$TESTS_FAILED${NC}"

exit $TESTS_FAILED
