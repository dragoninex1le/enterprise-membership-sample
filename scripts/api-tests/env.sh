#!/usr/bin/env bash

# Porth API Test Environment Configuration
set -euo pipefail

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# API Configuration
BASE_URL="${PORTH_API_URL:-https://1pdohk35u0.execute-api.us-east-1.amazonaws.com}"

# Test counters
TESTS_PASSED=0
TESTS_FAILED=0

# Helper function to mark a test as passed
pass() {
    local test_name="$1"
    echo -e "${GREEN}\u2713 PASS${NC} $test_name"
    TESTS_PASSED=$((TESTS_PASSED + 1))
}

# Helper function to mark a test as failed
fail() {
    local test_name="$1"
    local details="${2:-}"
    echo -e "${RED}\u2717 FAIL${NC} $test_name"
    if [[ -n "$details" ]]; then
        echo -e "${RED}  Details: $details${NC}"
    fi
    TESTS_FAILED=$((TESTS_FAILED + 1))
}

# Helper function to check HTTP status code
check_status() {
    local endpoint="$1"
    local expected_status="$2"
    local actual_status="$3"

    if [[ "$actual_status" == "$expected_status" ]]; then
        pass "GET $endpoint (HTTP $expected_status)"
        return 0
    else
        fail "GET $endpoint (expected $expected_status, got $actual_status)" "HTTP status mismatch"
        return 1
    fi
}

# Helper function to check status and response content
check_status_and_content() {
    local endpoint="$1"
    local expected_status="$2"
    local actual_status="$3"
    local response_file="$4"
    local content_check="$5"

    if [[ "$actual_status" != "$expected_status" ]]; then
        fail "GET $endpoint (expected $expected_status, got $actual_status)"
        return 1
    fi

    if grep -q "$content_check" "$response_file" 2>/dev/null; then
        pass "GET $endpoint (content validation)"
        return 0
    else
        fail "GET $endpoint (content validation failed)" "Expected to find '$content_check' in response"
        return 1
    fi
}

# Helper function to make API requests and capture status code
api_request() {
    local method="$1"
    local endpoint="$2"
    local output_file="$3"
    local data="${4:-}"

    if [[ -z "$data" ]]; then
        curl -s -L -w "\n%{http_code}" -o "$output_file" \
            -X "$method" \
            "$BASE_URL$endpoint"
    else
        curl -s -L -w "\n%{http_code}" -o "$output_file" \
            -X "$method" \
            -H "Content-Type: application/json" \
            -d "$data" \
            "$BASE_URL$endpoint"
    fi
}

# Helper function to extract JSON field using dot-notation path (e.g. "foo.bar.baz")
extract_json_field() {
    local json_file="$1"
    local field_path="$2"

    python3 - "$json_file" "$field_path" <<'PYEOF' 2>/dev/null || echo ""
import json, sys

json_file, field_path = sys.argv[1], sys.argv[2]
with open(json_file) as f:
    value = json.load(f)

if field_path:
    for part in field_path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            sys.exit(1)

print(json.dumps(value) if isinstance(value, (dict, list)) else value)
PYEOF
}

# Helper function to pretty-print JSON
pretty_json() {
    local json_file="$1"
    python3 -m json.tool "$json_file" 2>/dev/null || cat "$json_file"
}

export BASE_URL TESTS_PASSED TESTS_FAILED RED GREEN YELLOW BLUE NC
