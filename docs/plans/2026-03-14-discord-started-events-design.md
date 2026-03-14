# Discord Notification "Started" Events — Design

> **Date:** 2026-03-14
> **Status:** Approved

---

## Problem

Long-running operations (search queue execution, library sync) only send a notification on completion. There's no indication that work has begun, so the user has no context when they see a "complete" notification — they don't know when it started or that it was running at all.

## Solution

Add two new "started" notification methods that fire at the beginning of search execution and library sync. These piggyback on existing event toggles (no new toggles, no schema changes, no UI changes).

## New Notification Embeds

### Search Started

- **Method:** `send_search_started(search_name, instance_name, strategy, estimated_items)`
- **Color:** Blue (informational, `0x3498DB`)
- **Title:** `Search Started: {search_name}`
- **Body:**
  ```
  Instance: {instance_name}
  Strategy: {strategy}
  Items to evaluate: {estimated_items}
  ```
- **Toggle:** Shares `search_triggered` event toggle

### Library Sync Started

- **Method:** `send_library_sync_started(instance_count)`
- **Color:** Blue (informational, `0x3498DB`)
- **Title:** `Library Sync Started`
- **Body:** `Syncing {instance_count} instance(s)...`
- **Toggle:** Shares `library_sync` event toggle

## Dispatch Locations

- **Search started:** `services/search_queue.py` — at the top of the search execution method, before the item loop. Same dispatch pattern as `_notify_search_summary()`.
- **Library sync started:** `api/library.py` — at the start of the sync background task, before the per-instance loop.

## Files Changed

| File | Change |
|------|--------|
| `services/discord.py` | Add `send_search_started()` and `send_library_sync_started()` |
| `services/search_queue.py` | Add `_notify_search_started()` dispatch at execution start |
| `api/library.py` | Add sync-started dispatch at background task start |
| `tests/unit/test_discord_notifications.py` | Tests for new methods |

## What Does NOT Change

- `DEFAULT_EVENTS` dict
- `NotificationConfig` model
- Settings UI checkboxes
- Setup wizard notifications step
- Notification API endpoints or schemas
