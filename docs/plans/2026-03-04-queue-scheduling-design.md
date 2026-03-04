# Queue Scheduling Improvements — Design Document

**Feature #23** | **Target Release**: v1.3.0
**Date**: 2026-03-04

## Problem

All search queues run on fixed intervals ("every N hours"). Users can't schedule searches at specific times ("2 AM daily") or on specific days ("weekdays only"). Multiple queues starting at the same time can overwhelm indexers (thundering herd).

## Scope

### Schedule Modes

| Mode | Trigger | Example |
|------|---------|---------|
| **Interval** (existing) | Every N hours | "Every 4 hours" |
| **Daily** (new) | At HH:MM every day | "At 02:00 every day" |
| **Weekly** (new) | At HH:MM on selected days | "At 02:00 on Mon, Wed, Fri" |

### Jitter

All modes get a `jitter_minutes` field (0-15, default 0). APScheduler's `IntervalTrigger` and `CronTrigger` natively support `jitter` in seconds. No custom logic needed — pass `jitter=jitter_minutes * 60`.

### Data Model

New columns on `SearchQueue` (all with `server_default` for existing rows):

| Column | Type | Default | Used by |
|--------|------|---------|---------|
| `schedule_mode` | String(10) | `"interval"` | All modes |
| `schedule_time` | String(5) | `None` | Daily, Weekly ("HH:MM") |
| `schedule_days` | String(20) | `None` | Weekly ("mon,wed,fri") |
| `jitter_minutes` | Integer | `0` | All modes |

Existing `interval_hours` and `is_recurring` stay unchanged for backward compatibility.

### Scheduler Changes

In `schedule_queue()`:
- `"interval"` → `IntervalTrigger(hours=N, jitter=J)`
- `"daily"` → `CronTrigger(hour=H, minute=M, jitter=J)`
- `"weekly"` → `CronTrigger(day_of_week=days, hour=H, minute=M, jitter=J)`

### UI Changes

When "Recurring" is checked, show schedule mode selector:
- **Every N hours** — existing number input
- **Daily at** — time picker (HH:MM)
- **Weekly at** — day checkboxes (Mon-Sun) + time picker
- **Jitter** — number input (0-15 min), shown for all modes

### Presets Update

| Preset | Mode | Schedule |
|--------|------|----------|
| Aggressive Missing | interval | Every 1h |
| Weekly Cutoff Unmet | weekly | Mon/Thu at 03:00 |
| New Releases | interval | Every 4h |

## Not Building
- Multiple time windows per day
- Blackout periods
- Timezone selection (uses server time)
