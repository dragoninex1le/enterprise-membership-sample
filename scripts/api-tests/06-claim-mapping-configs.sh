#!/usr/bin/env bash

# Porth API Claim Mapping Configs Tests
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

echo -e "${BLUE}=== Porth API Claim Mapping Configs Tests ===${NC}\n"

TENANT_ID="t-test-1"
RESPONSE_FILE="/tmp/porth-test-claim-configs.json"

echo "Test 1: POST /claim-mapping-configs/?tenant_id=$TENANT_ID"
CONFIG_PAYLOAD=$(cat <<'EOF'
{
  "mapping_source": {
    "schema_version": "2.0",
    "lookup_tables": {},
    "fields": [
      {"name": "email", "source": "email", "type": "string", "required": true, "ops": [{"op": "lowercase"}]},
      {"name": "display_name", "source": "given_name", "type": "string", "default": "Unknown", "ops": [{"op": "trim"}]},
      {"name": "external_id", "source": "sub", "type": "string", "required": true, "ops": []},
      {"name": "roles", "source": "https://cart-agent.estyn.com/roles", "type": "collection", "ops": [{"op": "trim_lower"}, {"op": "resolve_roles"}]}
    ],
    "default_roles": ["authenticated"]
  },
  "example_jwt": {"email": "test@example.com", "sub": "ext-001", "given_name": "Test User", "https://cart-agent.estyn.com/roles": ["admin"]}
}
EOF
)
STATUS=$(api_request "POST" "/claim-mapping-configs/?tenant_id=$TENANT_ID" "$RESPONSE_FILE" "$CONFIG_PAYLOAD" | tail -1)
if [[ "$STATUS" == "200" || "$STATUS" == "201" ]]; then pass "POST /claim-mapping-configs (HTTP $STATUS)"
else fail "POST /claim-mapping-configs (expected 200/201, got $STATUS)"; fi

COMPILED_SOURCE=$(extract_json_field "$RESPONSE_FILE" "compiled_source")
COMPILED_HASH=$(extract_json_field "$RESPONSE_FILE" "compiled_hash")
if [[ -n "$COMPILED_SOURCE" ]]; then pass "Response contains compiled_source"
else fail "Response missing compiled_source"; fi
if [[ ${#COMPILED_HASH} -eq 64 ]]; then pass "compiled_hash is SHA256 (64 chars)"
else fail "compiled_hash length is ${#COMPILED_HASH} (expected 64)"; fi

STATUS=$(api_request "GET" "/claim-mapping-configs/$TENANT_ID/latest" "$RESPONSE_FILE" | tail -1)
if [[ "$STATUS" == "200" ]]; then pass "GET /claim-mapping-configs/$TENANT_ID/latest (HTTP 200)"
else fail "GET /claim-mapping-configs/$TENANT_ID/latest (expected 200, got $STATUS)"; fi

STATUS=$(api_request "GET" "/claim-mapping-configs/$TENANT_ID/versions" "$RESPONSE_FILE" | tail -1)
if [[ "$STATUS" == "200" ]]; then pass "GET /claim-mapping-configs/$TENANT_ID/versions (HTTP 200)"
else fail "GET /claim-mapping-configs/$TENANT_ID/versions (expected 200, got $STATUS)"; fi

STATUS=$(api_request "POST" "/claim-mapping-configs/$TENANT_ID/rollback/1" "$RESPONSE_FILE" | tail -1)
if [[ "$STATUS" == "200" || "$STATUS" == "201" ]]; then pass "POST rollback/1 (HTTP $STATUS)"
else fail "POST rollback/1 (expected 200/201, got $STATUS)"; fi

echo ""
echo -e "${BLUE}=== Claim Mapping Configs Tests Summary ===${NC}"
echo -e "Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Failed: ${RED}$TESTS_FAILED${NC}"

exit $TESTS_FAILED
