#!/usr/bin/env bash

# Porth API Test Suite Runner
# PORTH-227: Updated to include negative test scripts
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     Porth API Test Suite (Positive + Negative)             ║${NC}"
echo -e "${BLUE}║     API Base URL: $BASE_URL${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}\n"

# Initialize global failure counter
TOTAL_FAILED=0

# Function to run a test script and accumulate failures
run_test_script() {
    local script_path="$1"

    echo -e "${BLUE}────────────────────────────────────────────────────────────${NC}"

    local script_exit=0
    bash "$script_path" || script_exit=$?

    # Each script exits with its failure count
    TOTAL_FAILED=$((TOTAL_FAILED + script_exit))

    echo ""
}

# Clear any previous test state files
rm -f /tmp/porth-test-*.json
rm -f /tmp/porth-neg-*.json

# ─── Positive Tests (existing smoke tests) ──────────────────────────────────────────
echo -e "${YELLOW}Starting positive tests...${NC}\n"

run_test_script "$SCRIPT_DIR/00-setup.sh"
run_test_script "$SCRIPT_DIR/01-health.sh"
run_test_script "$SCRIPT_DIR/02-permissions.sh"
run_test_script "$SCRIPT_DIR/03-roles.sh"
run_test_script "$SCRIPT_DIR/04-users.sh"
run_test_script "$SCRIPT_DIR/06-claim-mapping-configs.sh"

# ─── Negative Tests (PORTH-227) ──────────────────────────────────────────────────
echo -e "${YELLOW}Starting negative tests (PORTH-227)...${NC}\n"

run_test_script "$SCRIPT_DIR/10-neg-organizations.sh"
run_test_script "$SCRIPT_DIR/11-neg-tenants.sh"
run_test_script "$SCRIPT_DIR/12-neg-permissions.sh"
run_test_script "$SCRIPT_DIR/13-neg-roles.sh"
run_test_script "$SCRIPT_DIR/14-neg-users.sh"
run_test_script "$SCRIPT_DIR/15-neg-claim-mapping-configs.sh"
run_test_script "$SCRIPT_DIR/16-neg-org-units.sh"
run_test_script "$SCRIPT_DIR/17-neg-provisioning.sh"

# Print final summary
echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     Test Suite Summary                                     ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}\n"

if [[ $TOTAL_FAILED -eq 0 ]]; then
    echo -e "${GREEN}All tests passed!${NC}"
    echo -e "Status: ${GREEN}\u2713 SUCCESS${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed.${NC}"
    echo -e "Failed: ${RED}$TOTAL_FAILED${NC}"
    echo -e "Status: ${RED}\u2717 FAILURE${NC}"
    exit 1
fi
