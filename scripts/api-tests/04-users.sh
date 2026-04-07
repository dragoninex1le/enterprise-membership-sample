#!/usr/bin/env bash

# Porth API Users Tests
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

echo -e "${BLUE}=== Porth API Users Tests ===${NC}\n"

TENANT_ID="t-test-1"
EXTERNAL_ID="ext-user-1"
ORG_ID=$(python3 -c "import json; data = json.load(open('/tmp/porth-test-setup-ids.json')); print(data.get('org_id', '1'))" 2>/dev/null || echo "1")
EMAIL="test@example.com"
DISPLAY_NAME="Test User"
RESPONSE_FILE="/tmp/porth-test-users.json"
USER_FILE="/tmp/porth-test-user-id.json"
ROLES_FILE="/tmp/porth-test-role-ids.json"

echo '{}' > "$USER_FILE"

echo "Testing: POST /users/upsert (create test user)"
UPSERT_PAYLOAD=$(cat <<EOF
{"email": "$EMAIL", "display_name": "$DISPLAY_NAME"}
EOF
)
STATUS=$(api_request "POST" "/users/upsert?external_id=$EXTERNAL_ID&org_id=$ORG_ID&tenant_id=$TENANT_ID" "$RESPONSE_FILE" "$UPSERT_PAYLOAD" | tail -1)

if [[ "$STATUS" == "200" || "$STATUS" == "201" ]]; then
    USER_ID=$(python3 -c "import json; data = json.load(open('$RESPONSE_FILE')); print(data.get('id', data.get('user_id', '')))" 2>/dev/null || echo "")
    if [[ -n "$USER_ID" ]]; then
        pass "POST /users/upsert (HTTP $STATUS)"
        python3 -c "import json; data = json.load(open('$USER_FILE')); data['user_id'] = '$USER_ID'; json.dump(data, open('$USER_FILE', 'w'))"
    else
        fail "POST /users/upsert" "Could not extract user ID"
    fi
else
    fail "POST /users/upsert (expected 200/201, got $STATUS)"
fi

USER_ID=$(python3 -c "import json; data = json.load(open('$USER_FILE')); print(data.get('user_id', ''))" 2>/dev/null || echo "")

if [[ -n "$USER_ID" ]]; then
    STATUS=$(api_request "GET" "/users/$USER_ID" "$RESPONSE_FILE" | tail -1)
    if [[ "$STATUS" == "200" ]]; then pass "GET /users/$USER_ID (HTTP 200)"
    else fail "GET /users/$USER_ID (expected 200, got $STATUS)"; fi

    STATUS=$(api_request "PATCH" "/users/$USER_ID" "$RESPONSE_FILE" '{"display_name": "Updated Test User"}' | tail -1)
    if [[ "$STATUS" == "200" ]]; then pass "PATCH /users/$USER_ID (HTTP 200)"
    else fail "PATCH /users/$USER_ID (expected 200, got $STATUS)"; fi

    VIEWER_ROLE_ID=$(python3 -c "import json; data = json.load(open('$ROLES_FILE')); print(data.get('viewer', ''))" 2>/dev/null || echo "")
    if [[ -n "$VIEWER_ROLE_ID" ]]; then
        STATUS=$(api_request "POST" "/roles/users/$USER_ID/tenant/$TENANT_ID/roles/$VIEWER_ROLE_ID" "$RESPONSE_FILE" "" | tail -1)
        if [[ "$STATUS" == "200" || "$STATUS" == "201" ]]; then pass "Assign viewer role to user (HTTP $STATUS)"
        else fail "Assign viewer role (expected 200/201, got $STATUS)"; fi

        STATUS=$(api_request "GET" "/users/$USER_ID/roles?tenant_id=$TENANT_ID" "$RESPONSE_FILE" | tail -1)
        if [[ "$STATUS" == "200" ]]; then
            COUNT=$(python3 -c "import json; data = json.load(open('$RESPONSE_FILE')); print(len(data) if isinstance(data, list) else len(data.get('roles', [])))" 2>/dev/null || echo "0")
            if [[ "$COUNT" -ge 1 ]]; then pass "GET /users/$USER_ID/roles (HTTP 200, $COUNT roles)"
            else fail "GET /users/$USER_ID/roles (expected >=1, found $COUNT)"; fi
        else fail "GET /users/$USER_ID/roles (expected 200, got $STATUS)"; fi

        STATUS=$(api_request "GET" "/users/$USER_ID/permissions?tenant_id=$TENANT_ID" "$RESPONSE_FILE" | tail -1)
        if [[ "$STATUS" == "200" ]]; then pass "GET /users/$USER_ID/permissions (HTTP 200)"
        else fail "GET /users/$USER_ID/permissions (expected 200, got $STATUS)"; fi
    fi

    STATUS=$(api_request "POST" "/users/$USER_ID/suspend" "$RESPONSE_FILE" "" | tail -1)
    if [[ "$STATUS" == "200" ]]; then pass "POST /users/$USER_ID/suspend (HTTP 200)"
    else fail "POST /users/$USER_ID/suspend (expected 200, got $STATUS)"; fi

    STATUS=$(api_request "POST" "/users/$USER_ID/reactivate" "$RESPONSE_FILE" "" | tail -1)
    if [[ "$STATUS" == "200" ]]; then pass "POST /users/$USER_ID/reactivate (HTTP 200)"
    else fail "POST /users/$USER_ID/reactivate (expected 200, got $STATUS)"; fi
fi

STATUS=$(api_request "GET" "/users/nonexistent-user-id" "$RESPONSE_FILE" | tail -1)
if [[ "$STATUS" == "404" ]]; then pass "GET /users/nonexistent (HTTP 404)"
else fail "GET /users/nonexistent (expected 404, got $STATUS)"; fi

echo ""
echo -e "${BLUE}=== Users Tests Summary ===${NC}"
echo -e "Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Failed: ${RED}$TESTS_FAILED${NC}"

exit $TESTS_FAILED
