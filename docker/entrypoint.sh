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

# Drop to non-root user and execute the command
log "Switching to appuser and starting application..."
exec gosu appuser "$@"
