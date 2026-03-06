#!/bin/bash
set -e

# Entrypoint script for Windows compatibility
# Runs as root since Windows Docker volumes don't handle Linux permissions properly

# Function to log messages
log() {
    echo "[entrypoint] $1"
}

log "Starting Splintarr entrypoint..."

# Create symlink so relative data paths (e.g. "data/posters") from WORKDIR /app
# resolve to the persistent Docker volume at /data.
# Without this, posters are written to ephemeral /app/data/ and lost on rebuild.
if [ ! -L /app/data ]; then
    # Symlink should exist from Dockerfile build, but create if missing
    rm -rf /app/data 2>/dev/null || true
    ln -sf /data /app/data 2>/dev/null || log "Note: /app/data symlink already exists or filesystem is read-only"
    [ -L /app/data ] && log "Created symlink /app/data -> /data"
fi

# Verify secrets are accessible
if [ -d "/run/secrets" ]; then
    log "Verifying Docker secrets..."
    for secret in db_key secret_key pepper; do
        if [ -f "/run/secrets/$secret" ]; then
            size=$(wc -c < "/run/secrets/$secret")
            log "Secret $secret: ${size} bytes"
        else
            log "WARNING: Secret file /run/secrets/$secret not found!"
        fi
    done
else
    log "WARNING: /run/secrets directory not found!"
fi

# Verify /data directory is writable
if [ -d "/data" ]; then
    log "Verifying /data directory is writable..."
    if touch /data/.write_test 2>/dev/null; then
        rm -f /data/.write_test
        log "Write test successful"
    else
        log "ERROR: Cannot write to /data directory!"
        exit 1
    fi
else
    log "ERROR: /data directory does not exist!"
    exit 1
fi

# Log configuration for debugging
log "Configuration:"
log "  Database path: /data/splintarr.db"
log "  DATABASE_KEY_FILE: ${DATABASE_KEY_FILE:-not set}"
log "  SECRET_KEY_FILE: ${SECRET_KEY_FILE:-not set}"
log "  PEPPER_FILE: ${PEPPER_FILE:-not set}"

# Fix ownership of writable directories (needed on Windows where bind mounts are root-owned)
for dir in /data /app/logs; do
    if [ -d "$dir" ]; then
        chown -R appuser:appuser "$dir" 2>/dev/null || log "Note: could not chown $dir (may already be correct)"
    fi
done

log "Dropping privileges to appuser..."
exec gosu appuser "$@"
