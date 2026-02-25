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

# Test if appuser can write to /data
log "Testing write permissions..."
if gosu appuser touch /data/.write_test 2>/dev/null; then
    rm -f /data/.write_test
    log "Write test successful - switching to appuser"
    exec gosu appuser "$@"
else
    log "WARNING: appuser cannot write to /data (Windows limitation)"
    log "Running as root for compatibility"
    exec "$@"
fi
