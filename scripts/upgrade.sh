#!/bin/bash
# Upgrade script for Splintarr
# Usage: ./scripts/upgrade.sh [version]

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Configuration
VERSION="${1:-latest}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${PROJECT_DIR}/docker/docker-compose.yml"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Splintarr Upgrade${NC}"
echo -e "${GREEN}Target Version: ${VERSION}${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Get current version
CURRENT_VERSION=$(docker inspect splintarr --format='{{index .Config.Labels "org.opencontainers.image.version"}}' 2>/dev/null || echo "unknown")
echo -e "Current version: ${CURRENT_VERSION}"
echo -e "Target version: ${VERSION}"
echo ""

# Confirm upgrade
if [ "${CURRENT_VERSION}" == "${VERSION}" ]; then
    echo -e "${YELLOW}Already running version ${VERSION}${NC}"
    echo -e "${YELLOW}Force upgrade? (y/N)${NC}"
    read -r response
    if [ "$response" != "y" ]; then
        exit 0
    fi
fi
echo ""

# Pre-upgrade checks
echo -e "${YELLOW}[1/8] Pre-upgrade checks...${NC}"

# Check if container is running
if ! docker ps | grep -q splintarr; then
    echo -e "${RED}Error: Container is not running${NC}"
    exit 1
fi

# Check disk space (need at least 1GB free)
FREE_SPACE=$(df -BG "${PROJECT_DIR}" | tail -1 | awk '{print $4}' | sed 's/G//')
if [ "${FREE_SPACE}" -lt 1 ]; then
    echo -e "${RED}Error: Insufficient disk space (need 1GB, have ${FREE_SPACE}GB)${NC}"
    exit 1
fi

echo -e "${GREEN}[OK] Pre-upgrade checks passed${NC}"
echo ""

# Automatic backup
echo -e "${YELLOW}[2/8] Creating automatic backup...${NC}"
BACKUP_FILE="${PROJECT_DIR}/backups/pre-upgrade-${CURRENT_VERSION}-$(date +%Y%m%d-%H%M%S).tar.gz"
"${PROJECT_DIR}/scripts/backup.sh" "${PROJECT_DIR}/backups" > /dev/null 2>&1
echo -e "${GREEN}[OK] Backup created${NC}"
echo ""

# Pull/build new version
echo -e "${YELLOW}[3/8] Building new version...${NC}"
cd "${PROJECT_DIR}"
export VERSION="${VERSION}"
export BUILD_DATE=$(date -u +'%Y-%m-%dT%H:%M:%SZ')
export VCS_REF=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

if [ "${VERSION}" == "latest" ] || [ ! -f "docker/Dockerfile" ]; then
    docker-compose -f "${COMPOSE_FILE}" pull
else
    docker-compose -f "${COMPOSE_FILE}" build --pull
fi
echo -e "${GREEN}[OK] New version ready${NC}"
echo ""

# Check for breaking changes
echo -e "${YELLOW}[4/8] Checking for breaking changes...${NC}"
BREAKING_CHANGES_FILE="${PROJECT_DIR}/UPGRADE_GUIDE.md"
if [ -f "${BREAKING_CHANGES_FILE}" ]; then
    if grep -q "Breaking Changes.*${VERSION}" "${BREAKING_CHANGES_FILE}"; then
        echo -e "${RED}[WARNING] BREAKING CHANGES DETECTED FOR VERSION ${VERSION}${NC}"
        echo -e "${YELLOW}Please review ${BREAKING_CHANGES_FILE}${NC}"
        echo -e "${YELLOW}Continue anyway? (yes/no)${NC}"
        read -r response
        if [ "$response" != "yes" ]; then
            exit 1
        fi
    else
        echo -e "${GREEN}[OK] No breaking changes detected${NC}"
    fi
else
    echo -e "${YELLOW}[WARNING] No upgrade guide found${NC}"
fi
echo ""

# Stop current version
echo -e "${YELLOW}[5/8] Stopping current version...${NC}"
docker-compose -f "${COMPOSE_FILE}" down
echo -e "${GREEN}[OK] Container stopped${NC}"
echo ""

# Run database migrations
echo -e "${YELLOW}[6/8] Running database migrations...${NC}"
if [ -f "${PROJECT_DIR}/alembic.ini" ]; then
    # Run migrations in temporary container
    docker-compose -f "${COMPOSE_FILE}" run --rm --entrypoint "alembic upgrade head" splintarr || {
        echo -e "${RED}[ERROR] Migration failed!${NC}"
        echo -e "${YELLOW}Rolling back...${NC}"
        "${PROJECT_DIR}/scripts/restore.sh" "${BACKUP_FILE}"
        exit 1
    }
    echo -e "${GREEN}[OK] Migrations completed${NC}"
else
    echo -e "${YELLOW}[WARNING] No migrations to run${NC}"
fi
echo ""

# Start new version
echo -e "${YELLOW}[7/8] Starting new version...${NC}"
docker-compose -f "${COMPOSE_FILE}" up -d
echo -e "${GREEN}[OK] Container started${NC}"
echo ""

# Verify health
echo -e "${YELLOW}[8/8] Verifying application health...${NC}"
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
    echo -e "${RED}[ERROR] Health check failed!${NC}"
    echo -e "${YELLOW}Rolling back to version ${CURRENT_VERSION}...${NC}"

    # Stop failed version
    docker-compose -f "${COMPOSE_FILE}" down

    # Restore from backup
    "${PROJECT_DIR}/scripts/restore.sh" "${BACKUP_FILE}"

    echo -e "${RED}Upgrade failed and rolled back${NC}"
    exit 1
fi
echo ""

# Post-upgrade verification
echo -e "${YELLOW}Running post-upgrade verification...${NC}"

# Check API is responding
if curl -f -s http://localhost:7337/health | grep -q "ok"; then
    echo -e "${GREEN}[OK] API responding${NC}"
else
    echo -e "${RED}[ERROR] API not responding correctly${NC}"
    exit 1
fi

# Check database is accessible
NEW_VERSION=$(docker inspect splintarr --format='{{index .Config.Labels "org.opencontainers.image.version"}}' 2>/dev/null || echo "unknown")
echo -e "${GREEN}[OK] Upgraded to version ${NEW_VERSION}${NC}"
echo ""

# Summary
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Upgrade completed successfully!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Previous version: ${CURRENT_VERSION}"
echo -e "New version: ${NEW_VERSION}"
echo -e "Backup location: ${BACKUP_FILE}"
echo ""
echo -e "${YELLOW}Post-upgrade checklist:${NC}"
echo -e "  ☐ Verify all instances are still configured"
echo -e "  ☐ Check search queues are running"
echo -e "  ☐ Review application logs"
echo -e "  ☐ Test authentication"
echo ""
echo -e "${YELLOW}Management commands:${NC}"
echo -e "  View logs:     docker-compose logs -f"
echo -e "  Check status:  docker-compose ps"
echo -e "  Rollback:      ./scripts/restore.sh ${BACKUP_FILE}"
echo ""

# Keep only last 5 upgrade backups
find "${PROJECT_DIR}/backups" -name "pre-upgrade-*.tar.gz" -type f | sort -r | tail -n +6 | xargs rm -f 2>/dev/null || true
