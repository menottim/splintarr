#!/bin/bash
# Complete setup script for Splintarr on Linux/macOS
#
# This script automates the complete setup process:
# - Checks prerequisites (Docker, Docker Compose)
# - Creates required directories (data, secrets)
# - Generates secure encryption keys
# - Optionally builds and starts the application
#
# Usage:
#   ./scripts/setup.sh                  # Interactive setup
#   ./scripts/setup.sh --auto-start     # Setup and start automatically
#   ./scripts/setup.sh --skip-secrets   # Skip secret generation
#
# Version: 1.0.0

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
WHITE='\033[1;37m'
GRAY='\033[0;37m'
NC='\033[0m' # No Color

# Output functions (matching generate-secrets.sh style)
error_exit() {
    echo -e "${RED}[ERROR] $1${NC}" >&2
    exit 1
}

success() {
    echo -e "${GREEN}[OK] $1${NC}"
}

warning() {
    echo -e "${YELLOW}[WARNING] $1${NC}"
}

info() {
    echo -e "${BLUE}[INFO] $1${NC}"
}

header() {
    echo ""
    echo -e "${BLUE}================================================================${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}================================================================${NC}"
    echo ""
}

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check if Docker daemon is running
docker_running() {
    docker ps >/dev/null 2>&1
}

# Determine the docker compose command (v2 plugin or standalone)
get_compose_command() {
    if docker compose version >/dev/null 2>&1; then
        echo "docker compose"
    elif command_exists docker-compose; then
        echo "docker-compose"
    else
        echo ""
    fi
}

# Parse command-line flags
AUTO_START=false
SKIP_SECRETS=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --auto-start)
            AUTO_START=true
            shift
            ;;
        --skip-secrets)
            SKIP_SECRETS=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --auto-start    Build and start the application after setup"
            echo "  --skip-secrets  Skip secret generation step"
            echo "  -h, --help      Show this help message"
            echo ""
            exit 0
            ;;
        *)
            error_exit "Unknown option: $1 (use --help for usage)"
            ;;
    esac
done

# Resolve project root (parent of scripts directory)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Work from the project root
cd "$PROJECT_DIR"

# === Main Setup ===

header "Splintarr - Linux/macOS Setup"

info "This script will set up Splintarr on your system."
echo ""

# --- Step 1: Check Prerequisites ---
echo -e "${WHITE}Step 1: Checking Prerequisites${NC}"
echo -e "${GRAY}----------------------------------------${NC}"
echo ""

# Check Docker
info "Checking for Docker..."
if ! command_exists docker; then
    echo -e "${RED}[ERROR] Docker is not installed or not in PATH${NC}" >&2
    echo ""
    echo -e "${YELLOW}Please install Docker from:${NC}"
    echo -e "${BLUE}  https://docs.docker.com/engine/install/${NC}"
    echo ""
    exit 1
fi
success "Docker found: $(docker --version)"

# Check Docker Compose
info "Checking for Docker Compose..."
COMPOSE_CMD=$(get_compose_command)
if [[ -z "$COMPOSE_CMD" ]]; then
    echo -e "${RED}[ERROR] Docker Compose is not installed or not in PATH${NC}" >&2
    echo ""
    echo -e "${YELLOW}Install Docker Compose:${NC}"
    echo -e "${BLUE}  https://docs.docker.com/compose/install/${NC}"
    echo ""
    exit 1
fi
success "Docker Compose found: $($COMPOSE_CMD version)"

# Check if Docker is running
info "Checking if Docker is running..."
if ! docker_running; then
    echo -e "${RED}[ERROR] Docker is not running${NC}" >&2
    echo ""
    echo -e "${YELLOW}Please start the Docker daemon and try again.${NC}"
    echo -e "${GRAY}  On Linux:  sudo systemctl start docker${NC}"
    echo -e "${GRAY}  On macOS:  Open Docker Desktop${NC}"
    echo ""
    exit 1
fi
success "Docker is running"

# --- Step 2: Create Required Directories ---
echo ""
echo -e "${WHITE}Step 2: Creating Required Directories${NC}"
echo -e "${GRAY}----------------------------------------${NC}"
echo ""

# Create data directory
info "Creating data directory..."
DATA_DIR="$PROJECT_DIR/data"
if [[ ! -d "$DATA_DIR" ]]; then
    mkdir -p "$DATA_DIR"
    success "Created: $DATA_DIR"
else
    info "Data directory already exists: $DATA_DIR"
fi

# Create secrets directory
info "Creating secrets directory..."
SECRETS_DIR="$PROJECT_DIR/secrets"
if [[ ! -d "$SECRETS_DIR" ]]; then
    mkdir -p "$SECRETS_DIR"
    chmod 700 "$SECRETS_DIR" 2>/dev/null || true
    success "Created: $SECRETS_DIR"
else
    info "Secrets directory already exists: $SECRETS_DIR"
fi

# --- Step 3: Generate Encryption Keys ---
echo ""
echo -e "${WHITE}Step 3: Generating Encryption Keys${NC}"
echo -e "${GRAY}----------------------------------------${NC}"
echo ""

if [[ "$SKIP_SECRETS" == true ]]; then
    warning "Skipping secret generation (--skip-secrets flag used)"
else
    # Check if secrets already exist
    EXISTING_SECRETS=()
    for file in db_key.txt secret_key.txt pepper.txt; do
        if [[ -f "$SECRETS_DIR/$file" ]]; then
            EXISTING_SECRETS+=("$file")
        fi
    done

    # Check if database exists
    DB_PATH="$PROJECT_DIR/data/splintarr.db"
    DB_EXISTS=false
    if [[ -f "$DB_PATH" ]]; then
        DB_EXISTS=true
    fi

    if [[ ${#EXISTING_SECRETS[@]} -gt 0 ]]; then
        echo ""
        echo -e "${YELLOW}================================================================${NC}"
        warning "EXISTING ENCRYPTION KEYS FOUND"
        echo -e "${YELLOW}================================================================${NC}"
        echo ""
        echo -e "${YELLOW}The following secret files already exist:${NC}"
        for file in "${EXISTING_SECRETS[@]}"; do
            echo -e "  - ${GRAY}secrets/$file${NC}"
        done
        echo ""
        echo -e "${YELLOW}IF YOU REGENERATE THESE KEYS:${NC}"
        echo -e "${WHITE}  1. The generate-secrets script will prompt you to confirm${NC}"
        echo -e "${RED}  2. Your existing encrypted database will become UNUSABLE${NC}"
        echo -e "${RED}  3. The script will AUTOMATICALLY DELETE the old database${NC}"

        if [[ "$DB_EXISTS" == true ]]; then
            echo ""
            echo -e "${YELLOW}An encrypted database was found at:${NC}"
            echo -e "  ${GRAY}$DB_PATH${NC}"
            echo ""
            echo -e "${RED}This file will be AUTOMATICALLY DELETED if you regenerate keys!${NC}"
            echo -e "${YELLOW}Make sure you have backups if you need to preserve any data.${NC}"
        fi

        echo ""
        echo -e "${BLUE}To keep your existing keys and database:${NC}"
        echo -e "${WHITE}  - Press CTRL+C now to cancel${NC}"
        echo -e "${WHITE}  - Or type anything other than 'yes' when prompted${NC}"
        echo ""
        echo -e "${YELLOW}================================================================${NC}"
        echo ""

        # Give user time to read
        sleep 3
    fi

    # Run generate-secrets.sh
    GENERATE_SCRIPT="$SCRIPT_DIR/generate-secrets.sh"
    if [[ -f "$GENERATE_SCRIPT" ]]; then
        info "Running secret generation script..."
        echo ""
        if ! bash "$GENERATE_SCRIPT"; then
            error_exit "Secret generation failed"
        fi
    else
        error_exit "Cannot find generate-secrets.sh at: $GENERATE_SCRIPT"
    fi
fi

# --- Step 4: Docker Setup ---
echo ""
echo -e "${WHITE}Step 4: Docker Setup${NC}"
echo -e "${GRAY}----------------------------------------${NC}"
echo ""

if [[ "$AUTO_START" == true ]]; then
    info "Building Docker image..."
    if ! $COMPOSE_CMD build; then
        error_exit "Docker build failed"
    fi
    success "Docker image built successfully"
    echo ""

    info "Starting application..."
    if ! $COMPOSE_CMD up -d; then
        error_exit "Failed to start application"
    fi
    success "Application started"
    echo ""

    # Wait for startup
    info "Waiting for application to initialize..."
    sleep 5

    # Check status
    info "Checking container status..."
    $COMPOSE_CMD ps
else
    info "Skipping automatic start (use --auto-start to build and start automatically)"
fi

# --- Setup Complete ---
echo ""
echo -e "${GREEN}================================================================${NC}"
echo -e "${GREEN}  Setup Complete!${NC}"
echo -e "${GREEN}================================================================${NC}"
echo ""

if [[ "$AUTO_START" == true ]]; then
    echo -e "${BLUE}Next Steps:${NC}"
    echo ""
    echo -e "${WHITE}  1. Check the application logs:${NC}"
    echo -e "${GRAY}     $COMPOSE_CMD logs -f${NC}"
    echo ""
    echo -e "${WHITE}  2. Open your browser to:${NC}"
    echo -e "${BLUE}     http://localhost:7337${NC}"
    echo ""
    echo -e "${WHITE}  3. Follow the setup wizard to create your admin account${NC}"
    echo ""
else
    echo -e "${BLUE}Next Steps:${NC}"
    echo ""
    echo -e "${WHITE}  1. Build the Docker image:${NC}"
    echo -e "${GRAY}     $COMPOSE_CMD build${NC}"
    echo ""
    echo -e "${WHITE}  2. Start the application:${NC}"
    echo -e "${GRAY}     $COMPOSE_CMD up -d${NC}"
    echo ""
    echo -e "${WHITE}  3. Check the logs:${NC}"
    echo -e "${GRAY}     $COMPOSE_CMD logs -f${NC}"
    echo ""
    echo -e "${WHITE}  4. Open your browser to:${NC}"
    echo -e "${BLUE}     http://localhost:7337${NC}"
    echo ""
    echo -e "${YELLOW}  Or run this script again with --auto-start to do all of this automatically.${NC}"
    echo ""
fi

# Note about key regeneration
if [[ "$SKIP_SECRETS" != true ]] && [[ ${#EXISTING_SECRETS[@]:-0} -gt 0 ]]; then
    echo ""
    echo -e "${BLUE}NOTE: If you regenerated encryption keys:${NC}"
    echo -e "${WHITE}  - The old database was automatically deleted${NC}"
    echo -e "${WHITE}  - A fresh database will be created on first startup${NC}"
    echo -e "${WHITE}  - You'll need to complete the setup wizard again${NC}"
    echo ""
fi

echo -e "${GRAY}For troubleshooting, see: docs/how-to-guides/troubleshoot.md${NC}"
echo ""

exit 0
