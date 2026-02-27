#!/bin/bash
# Health check script for Splintarr
# Usage: ./scripts/health-check.sh [url]

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Configuration
URL="${1:-http://localhost:7337}"
HEALTH_ENDPOINT="${URL}/health"
TIMEOUT=5

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Splintarr Health Check${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check if curl is available
if ! command -v curl &> /dev/null; then
    echo -e "${RED}Error: curl is not installed${NC}"
    exit 1
fi

# Check health endpoint
echo -e "${YELLOW}Checking: ${HEALTH_ENDPOINT}${NC}"
echo ""

if RESPONSE=$(curl -f -s -m "${TIMEOUT}" "${HEALTH_ENDPOINT}" 2>&1); then
    echo -e "${GREEN}[OK] Health endpoint responding${NC}"
    echo ""

    # Parse response (assuming JSON)
    if command -v jq &> /dev/null; then
        echo -e "${YELLOW}Response:${NC}"
        echo "${RESPONSE}" | jq .
    else
        echo -e "${YELLOW}Response:${NC}"
        echo "${RESPONSE}"
    fi
    echo ""

    # Check specific fields if present
    if echo "${RESPONSE}" | grep -q '"status"'; then
        STATUS=$(echo "${RESPONSE}" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
        if [ "${STATUS}" == "ok" ] || [ "${STATUS}" == "healthy" ]; then
            echo -e "${GREEN}[OK] Status: ${STATUS}${NC}"
        else
            echo -e "${RED}[ERROR] Status: ${STATUS}${NC}"
            exit 1
        fi
    fi

    # Check database
    if echo "${RESPONSE}" | grep -q '"database"'; then
        DB_STATUS=$(echo "${RESPONSE}" | grep -o '"database":"[^"]*"' | cut -d'"' -f4)
        if [ "${DB_STATUS}" == "ok" ] || [ "${DB_STATUS}" == "connected" ]; then
            echo -e "${GREEN}[OK] Database: ${DB_STATUS}${NC}"
        else
            echo -e "${RED}[ERROR] Database: ${DB_STATUS}${NC}"
            exit 1
        fi
    fi

    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}All checks passed!${NC}"
    echo -e "${GREEN}========================================${NC}"
    exit 0

else
    echo -e "${RED}[ERROR] Health endpoint not responding${NC}"
    echo -e "${RED}Error: ${RESPONSE}${NC}"
    echo ""

    # Additional diagnostics
    echo -e "${YELLOW}Running diagnostics...${NC}"
    echo ""

    # Check if service is listening
    if command -v nc &> /dev/null; then
        HOST=$(echo "${URL}" | sed -E 's|https?://([^:/]+).*|\1|')
        PORT=$(echo "${URL}" | sed -E 's|https?://[^:]+:?([0-9]+)?.*|\1|')
        PORT=${PORT:-7337}

        if nc -z "${HOST}" "${PORT}" 2>/dev/null; then
            echo -e "${GREEN}[OK] Port ${PORT} is listening${NC}"
        else
            echo -e "${RED}[ERROR] Port ${PORT} is not listening${NC}"
        fi
    fi

    # Check Docker container status
    if command -v docker &> /dev/null; then
        if docker ps | grep -q splintarr; then
            echo -e "${GREEN}[OK] Docker container is running${NC}"

            # Show recent logs
            echo ""
            echo -e "${YELLOW}Recent logs:${NC}"
            docker logs --tail 20 splintarr 2>&1
        else
            echo -e "${RED}[ERROR] Docker container is not running${NC}"

            # Check if container exists but stopped
            if docker ps -a | grep -q splintarr; then
                echo -e "${RED}Container exists but is stopped${NC}"
                echo ""
                echo -e "${YELLOW}Recent logs:${NC}"
                docker logs --tail 20 splintarr 2>&1
            fi
        fi
    fi

    echo ""
    echo -e "${RED}========================================${NC}"
    echo -e "${RED}Health check failed!${NC}"
    echo -e "${RED}========================================${NC}"
    exit 1
fi
