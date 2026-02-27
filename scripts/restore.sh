#!/bin/bash
# Restore script for Splintarr
# Usage: ./scripts/restore.sh <backup_file>

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Configuration
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_FILE="${1}"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Splintarr Restore${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Validation
if [ -z "${BACKUP_FILE}" ]; then
    echo -e "${RED}Error: No backup file specified${NC}"
    echo -e "Usage: $0 <backup_file>"
    exit 1
fi

if [ ! -f "${BACKUP_FILE}" ]; then
    echo -e "${RED}Error: Backup file not found: ${BACKUP_FILE}${NC}"
    exit 1
fi

# Verify checksum if available
if [ -f "${BACKUP_FILE}.sha256" ]; then
    echo -e "${YELLOW}[1/7] Verifying backup integrity...${NC}"
    if command -v sha256sum &> /dev/null; then
        if sha256sum -c "${BACKUP_FILE}.sha256" 2>/dev/null; then
            echo -e "${GREEN}[OK] Checksum verified${NC}"
        else
            echo -e "${RED}[ERROR] Checksum verification failed${NC}"
            echo -e "${YELLOW}Continue anyway? (y/N)${NC}"
            read -r response
            if [ "$response" != "y" ]; then
                exit 1
            fi
        fi
    elif command -v shasum &> /dev/null; then
        if shasum -a 256 -c "${BACKUP_FILE}.sha256" 2>/dev/null; then
            echo -e "${GREEN}[OK] Checksum verified${NC}"
        else
            echo -e "${RED}[ERROR] Checksum verification failed${NC}"
            echo -e "${YELLOW}Continue anyway? (y/N)${NC}"
            read -r response
            if [ "$response" != "y" ]; then
                exit 1
            fi
        fi
    fi
else
    echo -e "${YELLOW}[WARNING] No checksum file found, skipping verification${NC}"
fi
echo ""

# Confirm restore
echo -e "${YELLOW}This will restore from: ${BACKUP_FILE}${NC}"
echo -e "${RED}WARNING: This will OVERWRITE existing data!${NC}"
echo -e "${YELLOW}Continue? (yes/no)${NC}"
read -r response
if [ "$response" != "yes" ]; then
    echo -e "${YELLOW}Restore cancelled${NC}"
    exit 0
fi
echo ""

# Stop running container
echo -e "${YELLOW}[2/7] Stopping application...${NC}"
cd "${PROJECT_DIR}"
if [ -f "docker/docker-compose.yml" ]; then
    docker-compose -f docker/docker-compose.yml down 2>/dev/null || true
fi
echo -e "${GREEN}[OK] Application stopped${NC}"
echo ""

# Backup current state (safety measure)
echo -e "${YELLOW}[3/7] Creating safety backup of current state...${NC}"
SAFETY_BACKUP="${PROJECT_DIR}/backups/pre-restore-$(date +%Y%m%d-%H%M%S).tar.gz"
mkdir -p "${PROJECT_DIR}/backups"
if [ -d "${PROJECT_DIR}/data" ] || [ -d "${PROJECT_DIR}/secrets" ]; then
    tar -czf "${SAFETY_BACKUP}" -C "${PROJECT_DIR}" \
        $([ -d "data" ] && echo "data") \
        $([ -d "secrets" ] && echo "secrets") \
        $([ -f ".env" ] && echo ".env") \
        2>/dev/null || true
    echo -e "${GREEN}[OK] Safety backup created: ${SAFETY_BACKUP}${NC}"
else
    echo -e "${YELLOW}[WARNING] Nothing to backup${NC}"
fi
echo ""

# Extract backup
echo -e "${YELLOW}[4/7] Extracting backup archive...${NC}"
TEMP_DIR=$(mktemp -d)
tar -xzf "${BACKUP_FILE}" -C "${TEMP_DIR}"
BACKUP_NAME=$(ls -1 "${TEMP_DIR}" | head -1)
BACKUP_EXTRACT="${TEMP_DIR}/${BACKUP_NAME}"
echo -e "${GREEN}[OK] Backup extracted to temporary directory${NC}"
echo ""

# Display backup info
if [ -f "${BACKUP_EXTRACT}/BACKUP_INFO.txt" ]; then
    echo -e "${YELLOW}Backup information:${NC}"
    cat "${BACKUP_EXTRACT}/BACKUP_INFO.txt"
    echo ""
fi

# Restore data
echo -e "${YELLOW}[5/7] Restoring data...${NC}"

if [ -d "${BACKUP_EXTRACT}/data" ]; then
    rm -rf "${PROJECT_DIR}/data"
    cp -r "${BACKUP_EXTRACT}/data" "${PROJECT_DIR}/"
    chmod 700 "${PROJECT_DIR}/data"
    chmod 600 "${PROJECT_DIR}/data"/* 2>/dev/null || true
    echo -e "${GREEN}[OK] Data restored${NC}"
fi

if [ -d "${BACKUP_EXTRACT}/secrets" ]; then
    rm -rf "${PROJECT_DIR}/secrets"
    cp -r "${BACKUP_EXTRACT}/secrets" "${PROJECT_DIR}/"
    chmod 700 "${PROJECT_DIR}/secrets"
    chmod 600 "${PROJECT_DIR}/secrets"/* 2>/dev/null || true
    echo -e "${GREEN}[OK] Secrets restored${NC}"
fi

if [ -f "${BACKUP_EXTRACT}/.env" ]; then
    cp "${BACKUP_EXTRACT}/.env" "${PROJECT_DIR}/.env"
    chmod 600 "${PROJECT_DIR}/.env"
    echo -e "${GREEN}[OK] Environment file restored${NC}"
fi
echo ""

# Cleanup
echo -e "${YELLOW}[6/7] Cleaning up...${NC}"
rm -rf "${TEMP_DIR}"
echo -e "${GREEN}[OK] Temporary files removed${NC}"
echo ""

# Start application
echo -e "${YELLOW}[7/7] Starting application...${NC}"
cd "${PROJECT_DIR}"
if [ -f "docker/docker-compose.yml" ]; then
    docker-compose -f docker/docker-compose.yml up -d
    echo -e "${GREEN}[OK] Application started${NC}"

    # Wait for health check
    echo -e "${YELLOW}Waiting for application to be healthy...${NC}"
    sleep 5
    MAX_WAIT=60
    WAIT=0
    while [ $WAIT -lt $MAX_WAIT ]; do
        if curl -f -s http://localhost:7337/health > /dev/null 2>&1; then
            echo -e "${GREEN}[OK] Application is healthy${NC}"
            break
        fi
        echo -n "."
        sleep 2
        WAIT=$((WAIT + 2))
    done

    if [ $WAIT -ge $MAX_WAIT ]; then
        echo -e "${RED}[ERROR] Health check timeout${NC}"
        echo -e "${YELLOW}Check logs with: docker-compose logs${NC}"
    fi
else
    echo -e "${YELLOW}[WARNING] Docker Compose file not found, manual start required${NC}"
fi
echo ""

# Summary
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Restore completed successfully!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Restored from: ${BACKUP_FILE}"
echo -e "Safety backup: ${SAFETY_BACKUP}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo -e "1. Verify application is running: docker-compose ps"
echo -e "2. Check logs: docker-compose logs -f"
echo -e "3. Access application: http://localhost:7337"
echo ""
