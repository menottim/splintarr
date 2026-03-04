# Splintarr v1.2.1 Release Notes

**Release Date:** 2026-03-04
**Theme:** Notifications & Polish

## What's New in v1.2.1

### Discord Notification Enhancements (PRs #120)

- **Fix library_sync toggle** — existed in Settings UI but had no handler (bug fix)
- **Update available notification** — fires once when the update checker detects a newer version
- **Zero-result search notifications** — search summaries now sent even when nothing was found (red embed)
- **Grab confirmed notification** — fires after feedback check with grab/no-grab counts
- 2 new Settings toggles (Update Available, Grab Confirmed), setup wizard defaults updated

### Bug Fix: "Unknown" Series in Analytics (PR #121)

- Add `includeSeries=true` to Sonarr wanted/missing and wanted/cutoff API calls so episode records include series titles
- Fix analytics series name extraction — regex-based parsing replaces naive `split(" S")` which broke titles containing capital-S words (e.g., "The Simpsons", "Unknown Series")

### Auto Library Sync on Instance Add (PR #122)

- **Normal instance add** triggers library sync immediately in background
- **Setup wizard** defers sync until first dashboard visit (no sync during wizard flow)
- Idempotent — `_sync_in_progress` guard prevents duplicate syncs

### Fixes

- Notification exception isolation — notification failures no longer clear update checker state (dab0695)

## Upgrading from v1.2.0

Pull the latest image and restart:

```bash
docker-compose pull
docker-compose up -d
```

No database migrations required. New notification event toggles default to enabled for new installs; existing users will see them after re-saving notification settings.

## Feedback

Please report bugs and feedback at: https://github.com/menottim/splintarr/issues
