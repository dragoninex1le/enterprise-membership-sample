#!/usr/bin/env bash

# Porth API Permissions Tests
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

echo -e "${BLUE}=== Porth API Permissions Tests ===${NC}\n"

TENANT_ID="t-test-1"
APP_NAMESPACE="test-app"
RESPONSE_FILE="/tmp/porth-test-permissions.json"

# Test 1: POST /permissions - register batch of permissions
echo "Testing: POST /permissions (batch registration)"
PERMISSIONS_PAYLOAD=$(cat <<EOF
{
  "tenant_id": "$TENANT_ID",
  "app_namespace": "$APP_NAMESPACE",
  "permissions": [
    {
      "key": "orders.read",
      "display_name": "Read Orders",
      "category": "Orders",
      "description": "Read orders"
    },
    {
      "key": "orders.write",
      "display_name": "Write Orders",
      "category": "Orders",
      "description": "Write orders"
    },
    {
      "key": "orders.delete",
      "display_name": "Delete Orders",
      "category": "Orders",
      "description": "Delete orders"
    },
    {
      "key": "admin.full",
      "display_name": "Full Admin Access",
      "category": "Admin",
      "description": "Full admin access"
    }
  ]
}
EOF
)

STATUS=$(api_request "POST" "/permissions" "$RESPONSE_FILE" "$PERMISSIONS_PAYLOAD" | tail -1)

if [[ "$STATUS" == "200" || "$STATUS" == "201" ]]; then
    pass "POST /permissions (HTTP $STATUS)"
else
    fail "POST /permissions (expected 200/201, got $STATUS)"
fi

# Test 2: GET /permissions with query parameters
echo "Testing: GET /permissions?tenant_id=$TENANT_ID&app_namespace=$APP_NAMESPACE"
STATUS=$(api_request "GET" "/permissions?tenant_id=$TENANT_ID&app_namespace=$APP_NAMESPACE" "$RESPONSE_FILE" | tail -1)

if [[ "$STATUS" == "200" ]]; then
    PERM_COUNT=$(python3 -c "import json; data = json.load(open('$RESPONSE_FILE')); print(len(data) if isinstance(data, list) else len(data.get('permissions', data.get('registered', []))))" 2>/dev/null || echo "0")
    if [[ "$PERM_COUNT" -ge 4 ]]; then
        pass "GET /permissions (HTTP 200, found $PERM_COUNT permissions)"
    else
        fail "GET /permissions (expected at least 4 permissions, found $PERM_COUNT)"
    fi
else
    fail "GET /permissions (expected 200, got $STATUS)"
fi

# Test 3: GET specific permission by key
echo "Testing: GET /permissions/$TENANT_ID/$APP_NAMESPACE/orders.read"
STATUS=$(api_request "GET" "/permissions/$TENANT_ID/$APP_NAMESPACE/orders.read" "$RESPONSE_FILE" | tail -1)

if [[ "$STATUS" == "200" ]]; then
    pass "GET /permissions/$TENANT_ID/$APP_NAMESPACE/orders.read (HTTP 200)"
else
    fail "GET /permissions/$TENANT_ID/$APP_NAMESPACE/orders.read (expected 200, got $STATUS)"
fi

# Test 4: GET nonexistent permission (should return 404)
echo "Testing: GET /permissions/$TENANT_ID/$APP_NAMESPACE/nonexistent (negative test)"
STATUS=$(api_request "GET" "/permissions/$TENANT_ID/$APP_NAMESPACE/nonexistent" "$RESPONSE_FILE" | tail -1)

if [[ "$STATUS" == "404" ]]; then
    pass "GET /permissions/$TENANT_ID/$APP_NAMESPACE/nonexistent (HTTP 404 as expected)"
else
    fail "GET /permissions/$TENANT_ID/$APP_NAMESPACE/nonexistent (expected 404, got $STATUS)"
fi

# ─── PORTH-217: Invalid tenant negative tests ──────────────────────────────────────────
echo ""
echo -e "${YELLOW}── PORTH-217: Invalid tenant tests ──${NC}"
INVALID_TENANT="t-nonexistent-xyz"

# Test 5: POST /permissions with invalid tenant → 404
echo "Testing: POST /permissions with invalid tenant_id (expect 404)"
INVALID_PAYLOAD=$(cat <<EOF
{
  "tenant_id": "$INVALID_TENANT",
  "app_namespace": "$APP_NAMESPACE",
  "permissions": [
    {
      "key": "test.perm",
      "display_name": "Test",
      "category": "Test",
      "description": "Should fail"
    }
  ]
}
EOF
)

STATUS=$(api_request "POST" "/permissions" "$RESPONSE_FILE" "$INVALID_PAYLOAD" | tail -1)

if [[ "$STATUS" == "404" ]]; then
    pass "POST /permissions with invalid tenant (HTTP 404 as expected)"
else
    fail "POST /permissions with invalid tenant (expected 404, got $STATUS)"
fi

# Test 6: GET /permissions with invalid tenant → 404
echo "Testing: GET /permissions?tenant_id=$INVALID_TENANT (expect 404)"
STATUS=$(api_request "GET" "/permissions?tenant_id=$INVALID_TENANT" "$RESPONSE_FILE" | tail -1)

if [[ "$STATUS" == "404" ]]; then
    pass "GET /permissions with invalid tenant (HTTP 404 as expected)"
else
    fail "GET /permissions with invalid tenant (expected 404, got $STATUS)"
fi

echo ""
echo -e "${BLUE}=== Permissions Tests Summary ===${NC}"
echo -e "Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Failed: ${RED}$TESTS_FAILED${NC}"

exit $TESTS_FAILED
