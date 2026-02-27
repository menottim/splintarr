#!/bin/bash
# Generate secure secrets for Splintarr
# This script generates cryptographically secure random secrets for:
# - Database encryption (DATABASE_KEY)
# - JWT token signing (SECRET_KEY)
# - Password hashing pepper (PEPPER)

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Error handler
error_exit() {
    echo -e "${RED}[ERROR] $1${NC}" >&2
    exit 1
}

# Success message
success() {
    echo -e "${GREEN}[OK] $1${NC}"
}

# Warning message
warning() {
    echo -e "${YELLOW}[WARNING] $1${NC}"
}

# Info message
info() {
    echo -e "${BLUE}[INFO] $1${NC}"
}

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Validate generated secret
validate_secret() {
    local file="$1"
    local min_length="$2"

    if [[ ! -f "$file" ]]; then
        error_exit "Secret file not created: $file"
    fi

    local content
    content=$(cat "$file")

    if [[ -z "$content" ]]; then
        error_exit "Secret file is empty: $file"
    fi

    if [[ ${#content} -lt $min_length ]]; then
        error_exit "Secret too short in $file (expected at least $min_length chars, got ${#content})"
    fi

    # Check it's not all the same character
    if [[ "$content" =~ ^(.)\1+$ ]]; then
        error_exit "Secret appears to be non-random in $file"
    fi
}

echo ""
echo "================================================================"
echo "  Splintarr Secret Generation"
echo "================================================================"
echo ""

# Check for Python 3
if ! command_exists python3; then
    error_exit "Python 3 is required but not found. Please install Python 3.7+"
fi

info "Python 3 found: $(python3 --version)"

# Check Python can generate secrets
if ! python3 -c "import secrets" 2>/dev/null; then
    error_exit "Python 'secrets' module not available. Please upgrade to Python 3.6+"
fi

# Create secrets directory
SECRETS_DIR="./secrets"
info "Creating secrets directory: $SECRETS_DIR"

if ! mkdir -p "$SECRETS_DIR" 2>/dev/null; then
    error_exit "Failed to create secrets directory. Check permissions."
fi

# Set restrictive permissions on directory
if ! chmod 700 "$SECRETS_DIR" 2>/dev/null; then
    warning "Could not set directory permissions (chmod 700). Continuing..."
fi

# Check if secrets already exist
EXISTING_SECRETS=()
for file in db_key.txt secret_key.txt pepper.txt; do
    if [[ -f "$SECRETS_DIR/$file" ]]; then
        EXISTING_SECRETS+=("$file")
    fi
done

if [[ ${#EXISTING_SECRETS[@]} -gt 0 ]]; then
    echo ""
    echo "================================================================"
    echo -e "${YELLOW}WARNING: Existing secrets detected!${NC}"
    echo "================================================================"
    echo ""
    echo -e "${YELLOW}The following secret files already exist:${NC}"
    for file in "${EXISTING_SECRETS[@]}"; do
        echo "  - $file"
    done
    echo ""
    echo -e "${RED}IMPORTANT:${NC}"
    echo -e "${RED}  Regenerating secrets will make your existing database UNREADABLE!${NC}"
    echo -e "${RED}  All encrypted data will be permanently lost unless you have backups.${NC}"
    echo ""
    echo -e -n "${YELLOW}Do you want to continue and OVERWRITE existing secrets? (yes/no): ${NC}"
    read -r response

    if [[ "$response" != "yes" ]]; then
        echo ""
        echo -e "${GREEN}Operation cancelled. Existing secrets preserved.${NC}"
        echo ""
        exit 0
    fi
    echo ""
    echo -e "${YELLOW}Proceeding with secret regeneration...${NC}"
fi

echo ""
echo "Generating cryptographically secure secrets..."
echo ""

# Generate database encryption key (32 bytes = 256 bits, base64 encoded = ~43 chars)
info "Generating database encryption key..."
if ! python3 -c "import secrets; print(secrets.token_urlsafe(32))" > "$SECRETS_DIR/db_key.txt" 2>/dev/null; then
    error_exit "Failed to generate database key"
fi
validate_secret "$SECRETS_DIR/db_key.txt" 40
success "Database key generated (32 bytes, 256-bit)"

# Generate JWT secret key (64 bytes = 512 bits, base64 encoded = ~86 chars)
info "Generating JWT secret key..."
if ! python3 -c "import secrets; print(secrets.token_urlsafe(64))" > "$SECRETS_DIR/secret_key.txt" 2>/dev/null; then
    error_exit "Failed to generate secret key"
fi
validate_secret "$SECRETS_DIR/secret_key.txt" 80
success "JWT secret key generated (64 bytes, 512-bit)"

# Generate password hashing pepper (32 bytes = 256 bits, base64 encoded = ~43 chars)
info "Generating password hashing pepper..."
if ! python3 -c "import secrets; print(secrets.token_urlsafe(32))" > "$SECRETS_DIR/pepper.txt" 2>/dev/null; then
    error_exit "Failed to generate pepper"
fi
validate_secret "$SECRETS_DIR/pepper.txt" 40
success "Password pepper generated (32 bytes, 256-bit)"

echo ""
echo "Setting file permissions..."

# Set restrictive permissions on secret files
for file in "$SECRETS_DIR"/*.txt; do
    if [[ -f "$file" ]]; then
        if chmod 600 "$file" 2>/dev/null; then
            success "Permissions set on $(basename "$file") (read/write for owner only)"
        else
            warning "Could not set permissions on $(basename "$file"). Please set manually."
        fi
    fi
done

echo ""
echo "Verifying generated secrets..."

# Final verification
all_valid=true
for file in db_key.txt secret_key.txt pepper.txt; do
    filepath="$SECRETS_DIR/$file"
    if [[ -f "$filepath" ]] && [[ -s "$filepath" ]]; then
        size=$(stat -f%z "$filepath" 2>/dev/null || stat -c%s "$filepath" 2>/dev/null)
        success "$file verified (${size} bytes)"
    else
        error_exit "$file verification failed"
        all_valid=false
    fi
done

if [[ "$all_valid" == true ]]; then
    echo ""
    echo "================================================================"
    echo -e "${GREEN}SUCCESS: All secrets generated and verified!${NC}"
    echo "================================================================"
    echo ""
    echo "Generated files in $SECRETS_DIR:"
    echo "  - db_key.txt      (Database encryption key)"
    echo "  - secret_key.txt  (JWT signing key)"
    echo "  - pepper.txt      (Password hashing pepper)"
    echo ""
    echo -e "${YELLOW}CRITICAL SECURITY WARNINGS:${NC}"
    echo ""
    echo "  1. NEVER commit these files to version control"
    echo "  2. BACKUP these files securely (encrypted backup)"
    echo "  3. If you lose these files, you CANNOT decrypt your database"
    echo "  4. Store backups in multiple secure locations:"
    echo "     - Password manager (1Password, Bitwarden, etc.)"
    echo "     - Encrypted USB drive"
    echo "     - Secure cloud storage (encrypted)"
    echo ""
    echo -e "${BLUE}Next Steps:${NC}"
    echo ""
    echo "  1. Build the Docker image (first time setup):"
    echo "     docker-compose build"
    echo ""
    echo "  2. Start the application:"
    echo "     docker-compose up -d"
    echo ""
    echo "  3. Verify it's running:"
    echo "     docker-compose ps"
    echo ""
    echo "  4. Open your browser to:"
    echo "     http://localhost:7337"
    echo ""
    echo "  For complete setup instructions, see:"
    echo "  docs/how-to-guides/deploy-with-docker.md"
    echo ""
else
    error_exit "Secret validation failed. Please review errors above."
fi
