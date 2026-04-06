#!/usr/bin/env bash

# Porth API Test Setup — create the org + tenant used by all subsequent tests
# PORTH-217: Tests now require a valid tenant to exist before entity operations.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

echo -e "${BLUE}=== Porth API Test Setup ===${NC}\n"

TENANT_ID="t-test-1"
ORG_SLUG="test-org-smoke"
RESPONSE_FILE="/tmp/porth-test-setup.json"

# ─── Step 1: Create organization + first tenant ─────────────────────────
echo "Setup: POST /organizations (create org + tenant '$TENANT_ID')"
ORG_PAYLOAD=$(cat <<EOF
{
  "name": "Smoke Test Organization",
  "slug": "$ORG_SLUG",
  "tenant": {
    "tenant_id": "$TENANT_ID",
    "display_name": "Smoke Test Tenant",
    "environment_type": "development"
  }
}
EOF
)

STATUS=$(api_request "POST" "/organizations" "$RESPONSE_FILE" "$ORG_PAYLOAD" | tail -1)

if [[ "$STATUS" == "200" || "$STATUS" == "201" ]]; then
    # POST /organizations returns OrganizationCreateResponse: {"organization": {...}, "tenant": {...}}
    # The org id is nested under "organization.id", not at the top level.
    ORG_ID=$(extract_json_field "$RESPONSE_FILE" "organization.id")
    if [[ -z "$ORG_ID" ]]; then
        ORG_ID=$(extract_json_field "$RESPONSE_FILE" "organization.org_id")
    fi
    pass "POST /organizations (HTTP $STATUS, org created)"

    # Persist org_id for downstream scripts
    echo "{\"org_id\": \"$ORG_ID\", \"tenant_id\": \"$TENANT_ID\"}" > /tmp/porth-test-setup-ids.json

elif [[ "$STATUS" == "409" || "$STATUS" == "400" ]]; then
    # Org/tenant may already exist from a previous run — that's fine
    echo -e "${YELLOW}  ⚠ Org/tenant may already exist (HTTP $STATUS) — continuing${NC}"
    pass "POST /organizations (HTTP $STATUS — idempotent, org already exists)"

    # GET /organizations/slug/{slug} returns a bare Organization object (top-level id field)
    LOOKUP_STATUS=$(api_request "GET" "/organizations/slug/$ORG_SLUG" "$RESPONSE_FILE" | tail -1)
    if [[ "$LOOKUP_STATUS" == "200" ]]; then
        ORG_ID=$(extract_json_field "$RESPONSE_FILE" "id")
        if [[ -z "$ORG_ID" ]]; then
            ORG_ID=$(extract_json_field "$RESPONSE_FILE" "org_id")
        fi
        echo "{\"org_id\": \"$ORG_ID\", \"tenant_id\": \"$TENANT_ID\"}" > /tmp/porth-test-setup-ids.json
    fi
else
    fail "POST /organizations (expected 200/201/409, got $STATUS)"
    echo "  Response:"
    cat "$RESPONSE_FILE" 2>/dev/null | python3 -m json.tool 2>/dev/null || cat "$RESPONSE_FILE" 2>/dev/null
    echo ""
fi

# ─── Step 2: Verify the tenant is accessible ────────────────────────────
echo "Setup: GET /tenants/$TENANT_ID (verify tenant exists)"
STATUS=$(api_request "GET" "/tenants/$TENANT_ID" "$RESPONSE_FILE" | tail -1)

if [[ "$STATUS" == "200" ]]; then
    TENANT_STATUS=$(extract_json_field "$RESPONSE_FILE" "status")
    pass "GET /tenants/$TENANT_ID (HTTP 200, status=$TENANT_STATUS)"
else
    fail "GET /tenants/$TENANT_ID (expected 200, got $STATUS)" "Tenant must exist for subsequent tests"
fi

echo ""
echo -e "${BLUE}=== Setup Summary ===${NC}"
echo -e "Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Failed: ${RED}$TESTS_FAILED${NC}"

exit $TESTS_FAILED
