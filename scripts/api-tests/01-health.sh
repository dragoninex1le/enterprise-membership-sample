#!/usr/bin/env bash

# Porth API Health Check Tests
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

echo -e "${BLUE}=== Porth API Health Check ===${NC}\n"

# Test 1: GET /health
echo "Testing: GET /health"
RESPONSE_FILE="/tmp/porth-test-health.json"
STATUS=$(api_request "GET" "/health" "$RESPONSE_FILE" | tail -1)

if [[ "$STATUS" == "200" ]]; then
    if grep -q "healthy" "$RESPONSE_FILE" 2>/dev/null; then
        pass "GET /health (HTTP 200, verified 'healthy' in response)"
    else
        fail "GET /health (content validation)" "Expected 'healthy' in response"
    fi
else
    fail "GET /health (expected 200, got $STATUS)"
fi

# Test 2: GET /
echo "Testing: GET /"
RESPONSE_FILE="/tmp/porth-test-root.json"
STATUS=$(api_request "GET" "/" "$RESPONSE_FILE" | tail -1)

if [[ "$STATUS" == "200" ]]; then
    if grep -q "Porth User Management API" "$RESPONSE_FILE" 2>/dev/null; then
        pass "GET / (HTTP 200, verified 'Porth User Management API' in response)"
    else
        fail "GET / (content validation)" "Expected 'Porth User Management API' in response"
    fi
else
    fail "GET / (expected 200, got $STATUS)"
fi

echo ""
echo -e "${BLUE}=== Health Check Summary ===${NC}"
echo -e "Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Failed: ${RED}$TESTS_FAILED${NC}"

exit $TESTS_FAILED
