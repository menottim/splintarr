# Splintarr v1.0.1-alpha Release Notes

**Release Date:** 2026-03-02
**Status:** Alpha -- Ready for Testing

## What's New in v1.0.1-alpha

This is a polish and fixes release building on the v1.0.0-alpha foundation. No new major features, but significant dashboard improvements and bug fixes.

### Dashboard System Status Redesign (PR #108)

The System Status card on the dashboard has been reorganized from a flat instance list into three labeled sections:

- **Instances** — Sonarr/Radarr connection health (existing)
- **Integrations** — Discord and Prowlarr configuration status (new)
- **Internal Services** — Database health and scheduler status (new)

Both the server-rendered initial state and the 30-second polling JS render all three sections. The `/api/dashboard/system-status` endpoint now returns structured data for all sections and is rate-limited at 30 requests/minute.

### Dashboard Polish

- **Cutoff unmet count** shown in library stats card on the dashboard
- **Recent search activity** limited to 5 items (previously unbounded)
- **All-time stats per strategy** on the queue detail page
- **Hover tooltips** on non-obvious table headers across all pages

### Bug Fixes

- **Indexer health table tooltips** no longer clipped by overflow wrapper
- **Tooltip text styling** fixed across pseudo-elements (lowercase, lighter weight)
- **Docker footer version** now displays actual version instead of "vdev"
- **Library sync progress** no longer stuck on "Preparing sync" (broken auth call fixed)
- **Poster images** persist across container rebuilds (Docker volume fix)

### Infrastructure

- Poster-missing log level bumped from DEBUG to INFO
- Documentation screenshots regenerated for v1.0.0-alpha
- AI warning and author info moved under Acknowledgments in README

## Upgrading from v1.0.0-alpha

Pull the latest image and restart:

```bash
docker-compose pull
docker-compose up -d
```

No database migrations required. Existing data is preserved.

## Known Limitations

Same as v1.0.0-alpha:

- **Sonarr only** -- Radarr support is disabled in the alpha (backend code exists, UI is gated)
- **Single-worker only** -- Rate limiting is in-memory, doesn't share state across workers
- **No CSRF tokens** on setup wizard form submissions (mitigated by SameSite=strict cookies)
- **No config import** -- Export only in this release
- **Series-level cooldown** -- Cooldown applies at the series level in Sonarr, not per-episode (by design)
- **Tested on Windows Docker only** -- Linux/macOS should work but is unverified

## Feedback

Please report bugs and feedback at: https://github.com/menottim/splintarr/issues
