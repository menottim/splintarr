# Splintarr v1.3.2 Release Notes

**Release Date:** 2026-03-06
**Theme:** Windows Docker Fix

## Bug Fixes

- **Windows Docker crash on startup** -- The container crashed in a restart loop on Windows Docker Desktop with `PermissionError: [Errno 13] Permission denied: '/app/logs/all.log'`. The `./logs:/app/logs` bind mount is owned by root on Windows, but the app runs as `appuser` after privilege drop via `gosu`. The entrypoint now `chown`s writable directories (`/data`, `/app/logs`) before dropping privileges.
- **Dockerfile logs directory** -- `/app/logs` is now created with correct ownership at build time, ensuring the directory exists even without a bind mount.
- **Lighter healthcheck** -- Docker healthcheck switched from `httpx` (heavy third-party import) to stdlib `urllib.request`. Reduces healthcheck startup time and memory overhead, especially on resource-constrained machines where the old approach could contribute to healthcheck timeouts and container restarts.

## Upgrading from v1.3.1

```bash
docker-compose pull
docker-compose up -d
```

No database migrations required. Windows users who were experiencing restart loops should see the issue resolved immediately.

## Feedback

Please report bugs and feedback at: https://github.com/menottim/splintarr/issues
