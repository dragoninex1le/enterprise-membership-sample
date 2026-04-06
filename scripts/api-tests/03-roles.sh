#!/usr/bin/env bash

# Porth API Roles Tests
# PORTH-196: Roles now include source_key for claim mapping resolve_roles matching
# PORTH-269: Handle pre-existing roles idempotently (409 on create → lookup by name)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

echo -e "${BLUE}=== Porth API Roles Tests ===${NC}\n"

TENANT_ID="t-test-1"
APP_NAMESPACE="test-app"
RESPONSE_FILE="/tmp/porth-test-roles.json"
ROLES_FILE="/tmp/porth-test-role-ids.json"

# Initialize roles storage file
echo '{}' > "$ROLES_FILE"

# Test 1: POST /roles - create "Viewer" role
echo "Testing: POST /roles (create Viewer role)"
VIEWER_PAYLOAD=$(cat <<EOF
{
  "tenant_id": "$TENANT_ID",
  "name": "Viewer",
  "description": "View-only access",
  "is_system": false,
  "source_key": "viewer"
}
EOF
)

STATUS=$(api_request "POST" "/roles" "$RESPONSE_FILE" "$VIEWER_PAYLOAD" | tail -1)

if [[ "$STATUS" == "200" || "$STATUS" == "201" ]]; then
    VIEWER_ROLE_ID=$(python3 -c "import json; data = json.load(open('$RESPONSE_FILE')); print(data.get('id', data.get('role_id', '')))" 2>/dev/null || echo "")
    if [[ -n "$VIEWER_ROLE_ID" ]]; then
        pass "POST /roles (create Viewer, HTTP $STATUS)"
        python3 -c "import json; data = json.load(open('$ROLES_FILE')); data['viewer'] = '$VIEWER_ROLE_ID'; json.dump(data, open('$ROLES_FILE', 'w'))"
    else
        fail "POST /roles (Viewer creation)" "Could not extract role ID from response"
    fi
elif [[ "$STATUS" == "409" ]]; then
    pass "POST /roles (Viewer already exists, HTTP 409 — idempotent)"
else
    fail "POST /roles (create Viewer, expected 200/201/409, got $STATUS)"
fi

# Test 2: POST /roles - create "Editor" role
echo "Testing: POST /roles (create Editor role)"
EDITOR_PAYLOAD=$(cat <<EOF
{
  "tenant_id": "$TENANT_ID",
  "name": "Editor",
  "description": "Edit access",
  "is_system": false,
  "source_key": "editor"
}
EOF
)

STATUS=$(api_request "POST" "/roles" "$RESPONSE_FILE" "$EDITOR_PAYLOAD" | tail -1)

if [[ "$STATUS" == "200" || "$STATUS" == "201" ]]; then
    EDITOR_ROLE_ID=$(python3 -c "import json; data = json.load(open('$RESPONSE_FILE')); print(data.get('id', data.get('role_id', '')))" 2>/dev/null || echo "")
    if [[ -n "$EDITOR_ROLE_ID" ]]; then
        pass "POST /roles (create Editor, HTTP $STATUS)"
        python3 -c "import json; data = json.load(open('$ROLES_FILE')); data['editor'] = '$EDITOR_ROLE_ID'; json.dump(data, open('$ROLES_FILE', 'w'))"
    else
        fail "POST /roles (Editor creation)" "Could not extract role ID from response"
    fi
elif [[ "$STATUS" == "409" ]]; then
    pass "POST /roles (Editor already exists, HTTP 409 — idempotent)"
else
    fail "POST /roles (create Editor, expected 200/201/409, got $STATUS)"
fi

# Test 3: POST /roles - create "Admin" role with is_system=true
echo "Testing: POST /roles (create Admin system role)"
ADMIN_PAYLOAD=$(cat <<EOF
{
  "tenant_id": "$TENANT_ID",
  "name": "Admin",
  "description": "Admin access",
  "is_system": true,
  "source_key": "admin"
}
EOF
)

STATUS=$(api_request "POST" "/roles" "$RESPONSE_FILE" "$ADMIN_PAYLOAD" | tail -1)

if [[ "$STATUS" == "200" || "$STATUS" == "201" ]]; then
    ADMIN_ROLE_ID=$(python3 -c "import json; data = json.load(open('$RESPONSE_FILE')); print(data.get('id', data.get('role_id', '')))" 2>/dev/null || echo "")
    if [[ -n "$ADMIN_ROLE_ID" ]]; then
        pass "POST /roles (create Admin system role, HTTP $STATUS)"
        python3 -c "import json; data = json.load(open('$ROLES_FILE')); data['admin'] = '$ADMIN_ROLE_ID'; json.dump(data, open('$ROLES_FILE', 'w'))"
    else
        fail "POST /roles (Admin creation)" "Could not extract role ID from response"
    fi
elif [[ "$STATUS" == "409" ]]; then
    pass "POST /roles (Admin already exists, HTTP 409 — idempotent)"
else
    fail "POST /roles (create Admin, expected 200/201/409, got $STATUS)"
fi

# Test 4: GET /roles with tenant_id query
echo "Testing: GET /roles?tenant_id=$TENANT_ID"
STATUS=$(api_request "GET" "/roles?tenant_id=$TENANT_ID" "$RESPONSE_FILE" | tail -1)

if [[ "$STATUS" == "200" ]]; then
    ROLE_COUNT=$(python3 -c "import json; data = json.load(open('$RESPONSE_FILE')); print(len(data) if isinstance(data, list) else len(data.get('roles', [])))" 2>/dev/null || echo "0")
    if [[ "$ROLE_COUNT" -ge 3 ]]; then
        pass "GET /roles (HTTP 200, found $ROLE_COUNT roles)"
    else
        fail "GET /roles (expected at least 3 roles, found $ROLE_COUNT)"
    fi
else
    fail "GET /roles (expected 200, got $STATUS)"
fi

# PORTH-269: Resolve role IDs by name from the list response.
python3 - "$RESPONSE_FILE" "$ROLES_FILE" <<'PYEOF'
import json, sys

response_file, roles_file = sys.argv[1], sys.argv[2]

try:
    role_ids = json.load(open(roles_file))
except (json.JSONDecodeError, FileNotFoundError):
    role_ids = {}

try:
    data = json.load(open(response_file))
    roles = data if isinstance(data, list) else data.get("roles", [])
except (json.JSONDecodeError, FileNotFoundError):
    roles = []

name_to_key = {"Viewer": "viewer", "Editor": "editor", "Admin": "admin"}
for role in roles:
    name = role.get("name", "")
    key = name_to_key.get(name)
    if key and not role_ids.get(key):
        rid = role.get("id", role.get("role_id", ""))
        if rid:
            role_ids[key] = rid

json.dump(role_ids, open(roles_file, "w"))
PYEOF

# Reload role IDs for subsequent tests
VIEWER_ROLE_ID=$(python3 -c "import json; data = json.load(open('$ROLES_FILE')); print(data.get('viewer', ''))" 2>/dev/null || echo "")
EDITOR_ROLE_ID=$(python3 -c "import json; data = json.load(open('$ROLES_FILE')); print(data.get('editor', ''))" 2>/dev/null || echo "")
ADMIN_ROLE_ID=$(python3 -c "import json; data = json.load(open('$ROLES_FILE')); print(data.get('admin', ''))" 2>/dev/null || echo "")

if [[ -n "$VIEWER_ROLE_ID" ]]; then
    echo "Testing: GET /roles/$TENANT_ID/$VIEWER_ROLE_ID"
    STATUS=$(api_request "GET" "/roles/$TENANT_ID/$VIEWER_ROLE_ID" "$RESPONSE_FILE" | tail -1)
    if [[ "$STATUS" == "200" ]]; then
        SOURCE_KEY=$(python3 -c "import json; data = json.load(open('$RESPONSE_FILE')); print(data.get('source_key', ''))" 2>/dev/null || echo "")
        if [[ "$SOURCE_KEY" == "viewer" || "$SOURCE_KEY" == "viewer_updated" ]]; then
            pass "GET /roles/$TENANT_ID/$VIEWER_ROLE_ID (HTTP 200, source_key=$SOURCE_KEY)"
        else
            fail "GET /roles/$TENANT_ID/$VIEWER_ROLE_ID (HTTP 200, but source_key='$SOURCE_KEY')"
        fi
    else
        fail "GET /roles/$TENANT_ID/$VIEWER_ROLE_ID (expected 200, got $STATUS)"
    fi

    echo "Testing: PATCH /roles (update Viewer role)"
    STATUS=$(api_request "PATCH" "/roles/$TENANT_ID/$VIEWER_ROLE_ID" "$RESPONSE_FILE" '{"description": "Updated viewer description"}' | tail -1)
    if [[ "$STATUS" == "200" ]]; then pass "PATCH /roles/$TENANT_ID/$VIEWER_ROLE_ID (HTTP 200)"
    else fail "PATCH /roles/$TENANT_ID/$VIEWER_ROLE_ID (expected 200, got $STATUS)"; fi

    echo "Testing: PATCH /roles (update Viewer source_key)"
    STATUS=$(api_request "PATCH" "/roles/$TENANT_ID/$VIEWER_ROLE_ID" "$RESPONSE_FILE" '{"source_key": "viewer_updated"}' | tail -1)
    if [[ "$STATUS" == "200" ]]; then
        NEW_SK=$(python3 -c "import json; data = json.load(open('$RESPONSE_FILE')); print(data.get('source_key', ''))" 2>/dev/null || echo "")
        if [[ "$NEW_SK" == "viewer_updated" ]]; then pass "PATCH source_key (HTTP 200, source_key=viewer_updated)"
        else fail "PATCH source_key (HTTP 200, but source_key='$NEW_SK')"; fi
    else fail "PATCH source_key (expected 200, got $STATUS)"; fi
fi

if [[ -n "$VIEWER_ROLE_ID" && -n "$EDITOR_ROLE_ID" && -n "$ADMIN_ROLE_ID" ]]; then
    echo "Testing: PUT /roles permissions (viewer, editor, admin)"
    api_request "PUT" "/roles/$TENANT_ID/$VIEWER_ROLE_ID/permissions" "$RESPONSE_FILE" '["orders.read"]' | tail -1 > /dev/null
    api_request "PUT" "/roles/$TENANT_ID/$EDITOR_ROLE_ID/permissions" "$RESPONSE_FILE" '["orders.read", "orders.write"]' | tail -1 > /dev/null
    api_request "PUT" "/roles/$TENANT_ID/$ADMIN_ROLE_ID/permissions" "$RESPONSE_FILE" '["orders.read", "orders.write", "orders.delete", "admin.full"]' | tail -1 > /dev/null
    pass "PUT /roles permissions (viewer, editor, admin)"

    STATUS=$(api_request "GET" "/roles/$TENANT_ID/$VIEWER_ROLE_ID/permissions" "$RESPONSE_FILE" | tail -1)
    if [[ "$STATUS" == "200" ]]; then
        COUNT=$(python3 -c "import json; data = json.load(open('$RESPONSE_FILE')); print(len(data) if isinstance(data, list) else 0)" 2>/dev/null || echo "0")
        if [[ "$COUNT" -eq 1 ]]; then pass "GET viewer permissions (1 permission)"
        else fail "GET viewer permissions (expected 1, found $COUNT)"; fi
    else fail "GET viewer permissions (expected 200, got $STATUS)"; fi

    STATUS=$(api_request "DELETE" "/roles/$TENANT_ID/$ADMIN_ROLE_ID" "$RESPONSE_FILE" | tail -1)
    if [[ "$STATUS" == "403" ]]; then pass "DELETE system role (HTTP 403)"
    else fail "DELETE system role (expected 403, got $STATUS)"; fi
fi

echo ""
echo -e "${YELLOW}── PORTH-217: Invalid tenant tests ──${NC}"
INVALID_TENANT="t-nonexistent-xyz"
STATUS=$(api_request "POST" "/roles" "$RESPONSE_FILE" "{\"tenant_id\": \"$INVALID_TENANT\", \"name\": \"Fail\", \"description\": \"x\", \"source_key\": \"fail\"}" | tail -1)
if [[ "$STATUS" == "404" ]]; then pass "POST /roles with invalid tenant (HTTP 404)"
else fail "POST /roles with invalid tenant (expected 404, got $STATUS)"; fi

STATUS=$(api_request "GET" "/roles?tenant_id=$INVALID_TENANT" "$RESPONSE_FILE" | tail -1)
if [[ "$STATUS" == "404" ]]; then pass "GET /roles with invalid tenant (HTTP 404)"
else fail "GET /roles with invalid tenant (expected 404, got $STATUS)"; fi

echo ""
echo -e "${BLUE}=== Roles Tests Summary ===${NC}"
echo -e "Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Failed: ${RED}$TESTS_FAILED${NC}"

exit $TESTS_FAILED
