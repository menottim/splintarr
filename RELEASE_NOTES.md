# Splintarr v1.3.0 Release Notes

**Release Date:** 2026-03-04
**Theme:** Polish & Reach

## What's New in v1.3.0

### Indexer Budget Visibility (PR #123)

- **Visual progress bars** on dashboard indexer widget — color-coded green/gold/red by usage %
- **Budget alert notifications** via Discord at 80%+ usage with per-period dedup
- **Smart batch auto-sizing** — `budget_aware` toggle on queues reduces batch size when indexer budget is low
- Settings UI toggle for budget alerts, new `budget_aware` checkbox in queue modal

### Series Completion Cards (PR #124)

- **Dashboard card** — "Completion Progress" with 3 tabs: Most Incomplete, Closest to Complete, Recently Added
- **Library page section** — collapsible section above poster grid with scrollable cards
- **New API endpoint** — `GET /api/library/completion` returns sorted completion lists
- Demo data for completion cards on new installs

### Queue Scheduling Improvements (PR #125)

- **Daily mode** — "run at HH:MM every day" via APScheduler CronTrigger
- **Weekly mode** — "run at HH:MM on Mon/Wed/Fri" with day checkboxes
- **Jitter** — 0-15 min random offset to prevent thundering herd (APScheduler native)
- Schedule mode selector in queue creation/edit modal, presets updated
- Queue cards show mode-appropriate text ("Daily at 03:00", "Mon, Thu at 03:00")

### Config Import (PR #126)

- **Upload JSON** to restore instances, queues, exclusions, and notifications
- **Preview modal** with conflict detection and API key/webhook re-entry
- **Atomic import** with rollback on failure
- **SSRF protection** on imported instance URLs + field validation
- **Config export** now uses dynamic version (fixes stale "0.2.1")

### Code Quality & Security

- Code simplification: 12→6 DB queries on dashboard (eliminated double `get_onboarding_state`)
- N+1 elimination in config import (pre-loads instance names)
- Security hardening: SSRF check on imported URLs, field allowlists, user-scoped notification queries
- Duplicate code merged: cron trigger branches, schedule validation

## Upgrading from v1.2.x

Pull the latest image and restart:

```bash
docker-compose pull
docker-compose up -d
```

New columns (`schedule_mode`, `schedule_time`, `schedule_days`, `jitter_minutes`, `budget_aware`) are auto-created on startup with safe defaults. No manual database migrations required.

## Feedback

Please report bugs and feedback at: https://github.com/menottim/splintarr/issues
