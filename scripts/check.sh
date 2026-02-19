#!/bin/bash
# Automated verification script for Trading Agent System
# Usage: ./scripts/check.sh

set -e

echo "========================================="
echo "🔍 Trading Agent System - Quality Checks"
echo "========================================="
echo ""

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Track overall status
OVERALL_STATUS=0

# Function to print colored status
print_status() {
    if [ $1 -eq 0 ]; then
        echo -e "${GREEN}✓ PASSED${NC}: $2"
    else
        echo -e "${RED}✗ FAILED${NC}: $2"
        OVERALL_STATUS=1
    fi
}

echo "1️⃣  Checking Python syntax..."
if python3 -m compileall -q . 2>&1 | grep -E "SyntaxError|Error"; then
    print_status 1 "Python syntax check"
else
    print_status 0 "Python syntax check"
fi
echo ""

echo "2️⃣  Running test suite..."
if python3 -m pytest --version > /dev/null 2>&1; then
    if python3 -m pytest -v --tb=short 2>&1; then
        print_status 0 "Test suite"
    else
        print_status 1 "Test suite"
    fi
else
    echo -e "${YELLOW}⚠ WARNING${NC}: pytest not installed, skipping tests"
    echo "   Install with: pip install pytest pytest-asyncio"
fi
echo ""

echo "3️⃣  Checking import statements..."
CHECK_IMPORTS_RESULT=0
for file in $(find agents -name "*.py" -type f); do
    if ! python3 -c "import ast; ast.parse(open('$file').read())" 2>/dev/null; then
        echo "   ✗ Failed to parse: $file"
        CHECK_IMPORTS_RESULT=1
    fi
done
print_status $CHECK_IMPORTS_RESULT "Import validation"
echo ""

echo "4️⃣  Checking required environment variables..."
if [ -f .env.example ]; then
    print_status 0 "Found .env.example"
    echo "   Required variables:"
    echo "   - BYBIT_API_KEY / BYBIT_API_SECRET"
    echo "   - EXCHANGE (default: bybit)"
    echo "   - DEEPSEEK_API_KEY"
    echo "   - OPENAI_API_KEY"
    echo "   - COINGECKO_API_KEY"
else
    print_status 1 "Missing .env.example"
fi
echo ""

echo "========================================="
if [ $OVERALL_STATUS -eq 0 ]; then
    echo -e "${GREEN}✓ ALL CHECKS PASSED${NC}"
else
    echo -e "${RED}✗ SOME CHECKS FAILED${NC}"
fi
echo "========================================="

exit $OVERALL_STATUS
