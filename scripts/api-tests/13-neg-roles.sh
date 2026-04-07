#!/usr/bin/env bash

# Porth API Negative Tests — Roles
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

echo -e "${BLUE}=== Negative Tests: Roles ===${NC}\n"

TENANT_ID="t-test-1"
RESPONSE_FILE="/tmp/porth-neg-roles.json"
ROLES_FILE="/tmp/porth-test-role-ids.json"

ADMIN_ROLE_ID=$(python3 -c "import json; data = json.load(open('$ROLES_FILE')); print(data.get('admin', ''))" 2>/dev/null || echo "")

STATUS=$(api_request "GET" "/roles/$TENANT_ID/nonexistent-role-id-xyz" "$RESPONSE_FILE" | tail -1)
if [[ "$STATUS" == "404" ]]; then pass "NEG-R05: GET nonexistent role (HTTP 404)"
else fail "NEG-R05: GET nonexistent role (expected 404, got $STATUS)"; fi

STATUS=$(api_request "PATCH" "/roles/$TENANT_ID/nonexistent-role-id-xyz" "$RESPONSE_FILE" '{"description": "Updated"}' | tail -1)
if [[ "$STATUS" == "404" ]]; then pass "NEG-R06: PATCH nonexistent role (HTTP 404)"
else fail "NEG-R06: PATCH nonexistent role (expected 404, got $STATUS)"; fi

STATUS=$(api_request "DELETE" "/roles/$TENANT_ID/nonexistent-role-id-xyz" "$RESPONSE_FILE" | tail -1)
if [[ "$STATUS" == "404" ]]; then pass "NEG-R07: DELETE nonexistent role (HTTP 404)"
else fail "NEG-R07: DELETE nonexistent role (expected 404, got $STATUS)"; fi

if [[ -n "$ADMIN_ROLE_ID" ]]; then
    STATUS=$(api_request "DELETE" "/roles/$TENANT_ID/$ADMIN_ROLE_ID" "$RESPONSE_FILE" | tail -1)
    if [[ "$STATUS" == "403" ]]; then pass "NEG-R08: DELETE system role (HTTP 403)"
    else fail "NEG-R08: DELETE system role (expected 403, got $STATUS)"; fi
fi

STATUS=$(api_request "PUT" "/roles/$TENANT_ID/nonexistent-role-id/permissions" "$RESPONSE_FILE" '["test.perm"]' | tail -1)
if [[ "$STATUS" == "404" ]]; then pass "NEG-R09: PUT permissions on nonexistent role (HTTP 404)"
else fail "NEG-R09: PUT permissions nonexistent role (expected 404, got $STATUS)"; fi

STATUS=$(api_request "POST" "/roles" "$RESPONSE_FILE" '{}' | tail -1)
if [[ "$STATUS" == "400" || "$STATUS" == "422" ]]; then pass "NEG-R11: POST roles empty body (HTTP $STATUS)"
else fail "NEG-R11: POST roles empty body (expected 400/422, got $STATUS)"; fi

STATUS=$(api_request "POST" "/roles/users/nonexistent-user/tenant/$TENANT_ID/roles/some-role" "$RESPONSE_FILE" "" | tail -1)
if [[ "$STATUS" == "404" ]]; then pass "NEG-R12: assign role to nonexistent user (HTTP 404)"
else fail "NEG-R12: assign role to nonexistent user (expected 404, got $STATUS)"; fi

echo ""
echo -e "${BLUE}=== Roles Negative Tests Summary ===${NC}"
echo -e "Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Failed: ${RED}$TESTS_FAILED${NC}"

exit $TESTS_FAILED
