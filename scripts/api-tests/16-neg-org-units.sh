#!/usr/bin/env bash

# Porth API Negative Tests — Org Units
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

echo -e "${BLUE}=== Negative Tests: Org Units ===${NC}\n"

TENANT_ID="t-test-1"
RESPONSE_FILE="/tmp/porth-neg-org-units.json"
ROOT_OU_ID=""
CHILD_OU_ID=""

SETUP_PAYLOAD=$(printf '{"tenant_id":"%s","name":"Neg Test Root","type":"division","parent_id":null,"metadata":null}' "$TENANT_ID")
STATUS=$(api_request "POST" "/org-units/" "$RESPONSE_FILE" "$SETUP_PAYLOAD" | tail -1)
if [[ "$STATUS" == "200" || "$STATUS" == "201" ]]; then
    ROOT_OU_ID=$(python3 -c "import json; d=json.load(open('$RESPONSE_FILE')); print(d.get('id',d.get('org_unit_id','')))" 2>/dev/null || echo "")
fi

if [[ -n "$ROOT_OU_ID" ]]; then
    CHILD_PAYLOAD=$(printf '{"tenant_id":"%s","name":"Neg Child","type":"team","parent_id":"%s","metadata":null}' "$TENANT_ID" "$ROOT_OU_ID")
    STATUS=$(api_request "POST" "/org-units/" "$RESPONSE_FILE" "$CHILD_PAYLOAD" | tail -1)
    if [[ "$STATUS" == "200" || "$STATUS" == "201" ]]; then
        CHILD_OU_ID=$(python3 -c "import json; d=json.load(open('$RESPONSE_FILE')); print(d.get('id',d.get('org_unit_id','')))" 2>/dev/null || echo "")
    fi
fi

STATUS=$(api_request "GET" "/org-units/$TENANT_ID/nonexistent-ou-id-xyz" "$RESPONSE_FILE" | tail -1)
if [[ "$STATUS" == "404" ]]; then pass "NEG-OU05: GET nonexistent org unit (HTTP 404)"
else fail "NEG-OU05: GET nonexistent org unit (expected 404, got $STATUS)"; fi

STATUS=$(api_request "PATCH" "/org-units/$TENANT_ID/nonexistent-ou-id-xyz" "$RESPONSE_FILE" '{"name": "Updated"}' | tail -1)
if [[ "$STATUS" == "404" ]]; then pass "NEG-OU06: PATCH nonexistent org unit (HTTP 404)"
else fail "NEG-OU06: PATCH nonexistent (expected 404, got $STATUS)"; fi

if [[ -n "$ROOT_OU_ID" && -n "$CHILD_OU_ID" ]]; then
    STATUS=$(api_request "DELETE" "/org-units/$TENANT_ID/$ROOT_OU_ID" "$RESPONSE_FILE" | tail -1)
    if [[ "$STATUS" == "400" || "$STATUS" == "409" ]]; then pass "NEG-OU07: DELETE with children (HTTP $STATUS)"
    else fail "NEG-OU07: DELETE with children (expected 400/409, got $STATUS)"; fi
fi

STATUS=$(api_request "DELETE" "/org-units/$TENANT_ID/nonexistent-ou-id-xyz" "$RESPONSE_FILE" | tail -1)
if [[ "$STATUS" == "404" || "$STATUS" == "400" ]]; then pass "NEG-OU08: DELETE nonexistent (HTTP $STATUS)"
else fail "NEG-OU08: DELETE nonexistent (expected 404/400, got $STATUS)"; fi

echo -e "${YELLOW}Cleanup: removing test org units${NC}"
if [[ -n "${CHILD_OU_ID:-}" ]]; then
    api_request "DELETE" "/org-units/$TENANT_ID/$CHILD_OU_ID" "/tmp/porth-neg-cleanup.json" | tail -1 > /dev/null 2>&1 || true
fi
if [[ -n "${ROOT_OU_ID:-}" ]]; then
    api_request "DELETE" "/org-units/$TENANT_ID/$ROOT_OU_ID" "/tmp/porth-neg-cleanup.json" | tail -1 > /dev/null 2>&1 || true
fi

echo ""
echo -e "${BLUE}=== Org Units Negative Tests Summary ===${NC}"
echo -e "Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Failed: ${RED}$TESTS_FAILED${NC}"

exit $TESTS_FAILED
