#!/usr/bin/env bash

# Porth API Negative Tests — Claim Mapping Configs
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

echo -e "${BLUE}=== Negative Tests: Claim Mapping Configs ===${NC}\n"

TENANT_ID="t-test-1"
RESPONSE_FILE="/tmp/porth-neg-claim-configs.json"

STATUS=$(api_request "POST" "/claim-mapping-configs/?tenant_id=$TENANT_ID" "$RESPONSE_FILE" '{"example_jwt": null}' | tail -1)
if [[ "$STATUS" == "400" || "$STATUS" == "422" ]]; then pass "NEG-C01: missing mapping_source (HTTP $STATUS)"
else fail "NEG-C01: missing mapping_source (expected 400/422, got $STATUS)"; fi

STATUS=$(api_request "POST" "/claim-mapping-configs/?tenant_id=$TENANT_ID" "$RESPONSE_FILE" '{"mapping_source": {"schema_version": "99.0"}, "example_jwt": null}' | tail -1)
if [[ "$STATUS" == "422" || "$STATUS" == "400" ]]; then pass "NEG-C02: invalid schema_version (HTTP $STATUS)"
else fail "NEG-C02: invalid schema_version (expected 422/400, got $STATUS)"; fi

STATUS=$(api_request "GET" "/claim-mapping-configs/nonexistent-tenant-xyz/latest" "$RESPONSE_FILE" | tail -1)
if [[ "$STATUS" == "404" ]]; then pass "NEG-C05: GET latest nonexistent tenant (HTTP 404)"
else fail "NEG-C05: GET latest nonexistent tenant (expected 404, got $STATUS)"; fi

STATUS=$(api_request "GET" "/claim-mapping-configs/$TENANT_ID/99999" "$RESPONSE_FILE" | tail -1)
if [[ "$STATUS" == "404" ]]; then pass "NEG-C07: GET nonexistent version (HTTP 404)"
else fail "NEG-C07: GET nonexistent version (expected 404, got $STATUS)"; fi

STATUS=$(api_request "POST" "/claim-mapping-configs/$TENANT_ID/rollback/99999" "$RESPONSE_FILE" | tail -1)
if [[ "$STATUS" == "404" || "$STATUS" == "400" ]]; then pass "NEG-C08: rollback nonexistent version (HTTP $STATUS)"
else fail "NEG-C08: rollback nonexistent version (expected 404/400, got $STATUS)"; fi

echo ""
echo -e "${BLUE}=== Claim Mapping Configs Negative Tests Summary ===${NC}"
echo -e "Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Failed: ${RED}$TESTS_FAILED${NC}"

exit $TESTS_FAILED
