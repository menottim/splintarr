#!/bin/bash
set -e

# Entrypoint script that handles permissions and drops to non-root user

# Function to log messages
log() {
    echo "[entrypoint] $1"
}

log "Starting Vibe-Quality-Searcharr entrypoint..."

# Ensure /data directory exists and has correct permissions
if [ -d "/data" ]; then
    log "Setting permissions on /data directory..."
    # Try to fix permissions, but don't fail if we can't (Windows mounts)
    chown -R appuser:appuser /data 2>/dev/null || log "Note: Could not change ownership (this is normal on Windows)"
    chmod -R u+rw /data 2>/dev/null || log "Note: Could not change permissions (this is normal on Windows)"
    log "Permissions configured"
else
    log "WARNING: /data directory does not exist!"
fi

# Copy Docker secrets to a location accessible by appuser
# Docker secrets are mounted as root-only readable files, so we copy them
# to /tmp/secrets/ with appuser ownership before dropping privileges
SECRETS_COPIED=false
if [ -d "/run/secrets" ]; then
    log "Copying Docker secrets for appuser access..."
    mkdir -p /tmp/secrets

    # Copy each secret file if it exists
    for secret in db_key secret_key pepper; do
        if [ -f "/run/secrets/$secret" ]; then
            cp "/run/secrets/$secret" "/tmp/secrets/$secret"
            chown appuser:appuser "/tmp/secrets/$secret"
            chmod 400 "/tmp/secrets/$secret"
            log "Copied secret: $secret"
        fi
    done

    SECRETS_COPIED=true
    log "Secrets configured for appuser"
fi

# Test if appuser can write to /data
log "Testing write permissions..."
if gosu appuser touch /data/.write_test 2>/dev/null; then
    rm -f /data/.write_test
    log "Write test successful"

    # Verify secrets are readable by appuser
    if [ "$SECRETS_COPIED" = true ]; then
        if gosu appuser test -r /tmp/secrets/db_key; then
            log "Secret accessibility verified - switching to appuser"
        else
            log "WARNING: Secrets not readable by appuser, running as root instead"
            exec "$@"
            exit 0
        fi
    fi

    # Pass environment variables explicitly to ensure they're available to appuser
    if [ "$SECRETS_COPIED" = true ]; then
        log "Executing as appuser with environment variables"
        exec gosu appuser env \
            DATABASE_KEY_FILE=/tmp/secrets/db_key \
            SECRET_KEY_FILE=/tmp/secrets/secret_key \
            PEPPER_FILE=/tmp/secrets/pepper \
            "$@"
    else
        log "Executing as appuser without secret remapping"
        exec gosu appuser "$@"
    fi
else
    log "WARNING: appuser cannot write to /data (Windows limitation)"
    log "Running as root for compatibility"
    exec "$@"
fi
