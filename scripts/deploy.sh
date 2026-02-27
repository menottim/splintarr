#!/bin/bash
# Production deployment script for Splintarr
# Usage: ./scripts/deploy.sh [version]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
VERSION="${1:-latest}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${PROJECT_DIR}/docker/docker-compose.production.yml"
DATA_DIR="/var/lib/splintarr/data"
BACKUP_DIR="/var/backups/splintarr"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Splintarr Deployment${NC}"
echo -e "${GREEN}Version: ${VERSION}${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Pre-deployment checks
echo -e "${YELLOW}[1/8] Pre-deployment checks...${NC}"

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: Please run with sudo${NC}"
    exit 1
fi

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: Docker is not installed${NC}"
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}Error: Docker Compose is not installed${NC}"
    exit 1
fi

# Check if secrets exist
if [ ! -f "${PROJECT_DIR}/secrets/db_key.txt" ] || \
   [ ! -f "${PROJECT_DIR}/secrets/secret_key.txt" ] || \
   [ ! -f "${PROJECT_DIR}/secrets/pepper.txt" ]; then
    echo -e "${RED}Error: Secrets not found. Run ./scripts/generate-secrets.sh first${NC}"
    exit 1
fi

echo -e "${GREEN}[OK] Pre-deployment checks passed${NC}"
echo ""

# Backup existing data
echo -e "${YELLOW}[2/8] Backing up existing data...${NC}"
if [ -d "${DATA_DIR}" ]; then
    mkdir -p "${BACKUP_DIR}"
    BACKUP_FILE="${BACKUP_DIR}/backup-$(date +%Y%m%d-%H%M%S).tar.gz"
    tar -czf "${BACKUP_FILE}" -C "$(dirname ${DATA_DIR})" "$(basename ${DATA_DIR})" 2>/dev/null || true
    echo -e "${GREEN}[OK] Backup created: ${BACKUP_FILE}${NC}"
else
    echo -e "${YELLOW}[WARNING] No existing data to backup${NC}"
fi
echo ""

# Create data directory
echo -e "${YELLOW}[3/8] Setting up data directory...${NC}"
mkdir -p "${DATA_DIR}"
chown 1000:1000 "${DATA_DIR}"
chmod 700 "${DATA_DIR}"
echo -e "${GREEN}[OK] Data directory ready${NC}"
echo ""

# Pull latest images (if using registry)
echo -e "${YELLOW}[4/8] Building Docker image...${NC}"
cd "${PROJECT_DIR}"
export VERSION="${VERSION}"
export BUILD_DATE=$(date -u +'%Y-%m-%dT%H:%M:%SZ')
export VCS_REF=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

docker-compose -f "${COMPOSE_FILE}" build --pull
echo -e "${GREEN}[OK] Image built successfully${NC}"
echo ""

# Stop existing container
echo -e "${YELLOW}[5/8] Stopping existing container...${NC}"
docker-compose -f "${COMPOSE_FILE}" down || true
echo -e "${GREEN}[OK] Container stopped${NC}"
echo ""

# Start new container
echo -e "${YELLOW}[6/8] Starting new container...${NC}"
docker-compose -f "${COMPOSE_FILE}" up -d
echo -e "${GREEN}[OK] Container started${NC}"
echo ""

# Wait for health check
echo -e "${YELLOW}[7/8] Waiting for application to be healthy...${NC}"
MAX_WAIT=60
WAIT=0
while [ $WAIT -lt $MAX_WAIT ]; do
    if docker-compose -f "${COMPOSE_FILE}" ps | grep -q "healthy"; then
        echo -e "${GREEN}[OK] Application is healthy${NC}"
        break
    fi
    echo -n "."
    sleep 2
    WAIT=$((WAIT + 2))
done

if [ $WAIT -ge $MAX_WAIT ]; then
    echo -e "${RED}[ERROR] Health check timeout${NC}"
    echo -e "${YELLOW}Check logs with: docker-compose -f ${COMPOSE_FILE} logs${NC}"
    exit 1
fi
echo ""

# Post-deployment verification
echo -e "${YELLOW}[8/8] Post-deployment verification...${NC}"
if curl -f -s http://localhost:7337/health > /dev/null; then
    echo -e "${GREEN}[OK] Health endpoint responding${NC}"
else
    echo -e "${RED}[ERROR] Health endpoint not responding${NC}"
    exit 1
fi
echo ""

# Summary
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment completed successfully!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Version: ${VERSION}"
echo -e "URL: http://localhost:7337"
echo -e "Status: $(docker-compose -f ${COMPOSE_FILE} ps)"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo -e "1. Configure your reverse proxy (nginx/Traefik)"
echo -e "2. Set up SSL/TLS certificates"
echo -e "3. Access the setup wizard at http://localhost:7337/setup"
echo ""
echo -e "${YELLOW}Management commands:${NC}"
echo -e "  View logs:     docker-compose -f ${COMPOSE_FILE} logs -f"
echo -e "  Stop:          docker-compose -f ${COMPOSE_FILE} down"
echo -e "  Restart:       docker-compose -f ${COMPOSE_FILE} restart"
echo -e "  Backup:        ./scripts/backup.sh"
echo ""
