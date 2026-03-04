# Splintarr v1.1.1 Release Notes

**Release Date:** 2026-03-04
**Theme:** Update Checker

## What's New in v1.1.1

### Automatic Update Checker (PRs #117, #118)

- **Automatic version checking** via GitHub Releases API every 24 hours
- **Dismissible gold banner** on the dashboard when a newer version is available
- **Per-version dismissal** — dismissing v1.2.0 hides it until v1.3.0 is released
- **Settings page toggle** to enable/disable update checking with "Check Now" button
- 4 new API endpoints: `/api/updates/status`, `/check`, `/dismiss`, `/toggle`
- Graceful failure: if GitHub is unreachable, shows red error message (not misleading "up to date")
- Skips draft and pre-release GitHub releases
- 38 tests (20 service, 14 API, 4 integration)

### Fixes

- "Check Now" correctly shows failure message when GitHub is unreachable (PR #118)
- Increased GitHub API timeout from 5s to 10s for Docker environments

## Upgrading from v1.1.0

Pull the latest image and restart:

```bash
docker-compose pull
docker-compose up -d
```

No database migrations required. New columns (`dismissed_update_version`, `update_check_enabled`) are added automatically on first startup.

## Feedback

Please report bugs and feedback at: https://github.com/menottim/splintarr/issues
