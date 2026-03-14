# Fix Grab Confirmation (#130) — Design

> **Date:** 2026-03-14
> **Issue:** https://github.com/menottim/splintarr/issues/130
> **Status:** Approved

---

## Problem

Two bugs in grab confirmation:

1. **False grab detection.** The feedback check determines a "grab" by checking if `hasFile == True` on the episode 15 minutes after a search command completes. This doesn't verify that Splintarr's search caused the download — the file could have been pre-existing, downloaded by Sonarr's RSS monitoring, or manually imported. Result: inflated grab counts and claims of grabs that never happened.

2. **Dashboard vs queue count discrepancy.** The dashboard shows `SUM(LibraryItem.grabs_confirmed)` (lifetime, all queues), while queue detail counts `result=="grabbed"` in that specific run's `search_metadata` JSON. These are different scopes and will always diverge.

## Root Cause

- `feedback.py` uses `hasFile` as a proxy for "grab happened" — correlation, not causation
- Sonarr has a proper history API (`GET /api/v3/history` with `eventType=1`) that tracks actual grabs with timestamps and episode IDs, but Splintarr never uses it
- Dashboard and queue detail query different data stores with different scopes

## Solution

### 1. Add `get_history` method to Sonarr client

New method on the Sonarr client:
- Calls `GET /api/v3/history` with `episodeId` and `eventType=1` (grabbed) filters
- Returns recent history records with `date`, `episodeId`, `sourceTitle`, `downloadId`
- Page size of 10 (only need recent events)

### 2. Rewrite feedback check grab detection

Replace the `hasFile` check in `feedback.py` with:
1. Get the search command's issued timestamp (record at search time)
2. Query Sonarr history for grabbed events on that episode
3. Only count as "grabbed" if there's a history event with `eventType=1` dated **after** the search command was issued
4. Store `sourceTitle` from the history event in search metadata for auditability

### 3. Dashboard: switch to 7-day grab count

Replace `SUM(LibraryItem.grabs_confirmed)` with a query against SearchHistory from the last 7 days, counting `result=="grabbed"` entries in `search_metadata`. Matches the analytics card scope and uses corrected feedback data.

### 4. Reset existing grab data

Alembic migration to reset `LibraryItem.grabs_confirmed = 0` and `LibraryItem.last_grab_at = NULL` for all rows, since existing data is unreliable.

## Files Changed

| File | Change |
|------|--------|
| `services/sonarr.py` | Add `get_history(episode_id, event_type, since)` method |
| `services/feedback.py` | Replace `hasFile` check with history API check |
| `services/search_queue.py` | Record command issued timestamp in search metadata |
| `api/dashboard.py` | Switch grab count to 7-day SearchHistory-based query |
| `alembic/versions/xxx_reset_grabs.py` | Migration to zero out inflated data |
| Tests for all of the above |

## What Does NOT Change

- `LibraryItem.grabs_confirmed` field still exists (will be accurately incremented going forward)
- `LibraryItem.record_grab()` method still exists
- Discord grab notification logic (fires based on corrected data)
- Queue detail page grab display (already reads from search_metadata)
- Feedback check scheduling/timing (15-minute delay is still appropriate)
