#!/bin/bash
# Backup script for Splintarr
# Usage: ./scripts/backup.sh [destination]

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Configuration
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${PROJECT_DIR}/data"
SECRETS_DIR="${PROJECT_DIR}/secrets"
BACKUP_DEST="${1:-${PROJECT_DIR}/backups}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_NAME="splintarr-backup-${TIMESTAMP}"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Splintarr Backup${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Create backup directory
mkdir -p "${BACKUP_DEST}"

# Check what exists
echo -e "${YELLOW}[1/5] Checking backup sources...${NC}"
BACKUP_ITEMS=()

if [ -d "${DATA_DIR}" ]; then
    echo -e "${GREEN}[OK] Data directory found${NC}"
    BACKUP_ITEMS+=("data")
else
    echo -e "${YELLOW}[WARNING] No data directory found${NC}"
fi

if [ -d "${SECRETS_DIR}" ]; then
    echo -e "${GREEN}[OK] Secrets directory found${NC}"
    BACKUP_ITEMS+=("secrets")
else
    echo -e "${YELLOW}[WARNING] No secrets directory found${NC}"
fi

if [ -f "${PROJECT_DIR}/.env" ]; then
    echo -e "${GREEN}[OK] Environment file found${NC}"
    BACKUP_ITEMS+=(".env")
else
    echo -e "${YELLOW}[WARNING] No .env file found${NC}"
fi

if [ ${#BACKUP_ITEMS[@]} -eq 0 ]; then
    echo -e "${RED}Error: Nothing to backup${NC}"
    exit 1
fi
echo ""

# Create temporary backup directory
echo -e "${YELLOW}[2/5] Creating backup structure...${NC}"
TEMP_DIR=$(mktemp -d)
BACKUP_DIR="${TEMP_DIR}/${BACKUP_NAME}"
mkdir -p "${BACKUP_DIR}"
echo -e "${GREEN}[OK] Temporary directory: ${TEMP_DIR}${NC}"
echo ""

# Copy data
echo -e "${YELLOW}[3/5] Copying data...${NC}"

if [[ " ${BACKUP_ITEMS[@]} " =~ " data " ]]; then
    cp -r "${DATA_DIR}" "${BACKUP_DIR}/"
    echo -e "${GREEN}[OK] Data copied${NC}"
fi

if [[ " ${BACKUP_ITEMS[@]} " =~ " secrets " ]]; then
    cp -r "${SECRETS_DIR}" "${BACKUP_DIR}/"
    chmod 600 "${BACKUP_DIR}/secrets"/*
    echo -e "${GREEN}[OK] Secrets copied${NC}"
fi

if [[ " ${BACKUP_ITEMS[@]} " =~ " .env " ]]; then
    cp "${PROJECT_DIR}/.env" "${BACKUP_DIR}/"
    echo -e "${GREEN}[OK] Environment file copied${NC}"
fi

# Add metadata
cat > "${BACKUP_DIR}/BACKUP_INFO.txt" <<EOF
Splintarr Backup
Created: $(date)
Hostname: $(hostname)
Version: $(cat ${PROJECT_DIR}/pyproject.toml | grep "^version" | cut -d'"' -f2 || echo "unknown")
Contents: ${BACKUP_ITEMS[@]}
EOF

echo ""

# Create archive
echo -e "${YELLOW}[4/5] Creating archive...${NC}"
cd "${TEMP_DIR}"
tar -czf "${BACKUP_DEST}/${BACKUP_NAME}.tar.gz" "${BACKUP_NAME}"
BACKUP_FILE="${BACKUP_DEST}/${BACKUP_NAME}.tar.gz"
BACKUP_SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
echo -e "${GREEN}[OK] Archive created: ${BACKUP_FILE} (${BACKUP_SIZE})${NC}"
echo ""

# Cleanup
echo -e "${YELLOW}[5/5] Cleaning up...${NC}"
rm -rf "${TEMP_DIR}"
echo -e "${GREEN}[OK] Temporary files removed${NC}"
echo ""

# Calculate checksum
echo -e "${YELLOW}Calculating checksum...${NC}"
if command -v sha256sum &> /dev/null; then
    CHECKSUM=$(sha256sum "${BACKUP_FILE}" | cut -d' ' -f1)
    echo "${CHECKSUM}  ${BACKUP_NAME}.tar.gz" > "${BACKUP_FILE}.sha256"
    echo -e "${GREEN}[OK] SHA256: ${CHECKSUM}${NC}"
elif command -v shasum &> /dev/null; then
    CHECKSUM=$(shasum -a 256 "${BACKUP_FILE}" | cut -d' ' -f1)
    echo "${CHECKSUM}  ${BACKUP_NAME}.tar.gz" > "${BACKUP_FILE}.sha256"
    echo -e "${GREEN}[OK] SHA256: ${CHECKSUM}${NC}"
fi
echo ""

# Summary
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Backup completed successfully!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Backup file: ${BACKUP_FILE}"
echo -e "Size: ${BACKUP_SIZE}"
echo -e "Contents: ${BACKUP_ITEMS[@]}"
echo ""
echo -e "${YELLOW}To restore from this backup:${NC}"
echo -e "  ./scripts/restore.sh ${BACKUP_FILE}"
echo ""
echo -e "${RED}[WARNING] IMPORTANT: Store this backup securely!${NC}"
echo -e "${RED}  It contains encryption keys and sensitive data.${NC}"
echo ""

# Cleanup old backups (keep last 7 days)
echo -e "${YELLOW}Cleaning up old backups (keeping last 7 days)...${NC}"
find "${BACKUP_DEST}" -name "splintarr-backup-*.tar.gz" -type f -mtime +7 -delete 2>/dev/null || true
find "${BACKUP_DEST}" -name "splintarr-backup-*.sha256" -type f -mtime +7 -delete 2>/dev/null || true
echo -e "${GREEN}[OK] Old backups cleaned${NC}"
echo ""
