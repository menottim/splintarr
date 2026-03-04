# Indexer Budget Visibility & Forecasting — Design Document

**Feature #21** | **Target Release**: v1.3.0
**Date**: 2026-03-04

## Problem

Users can't see how much of their indexer API budget has been consumed. The dashboard widget shows raw numbers ("12 of 50") but no visual indicator of urgency. There's no alerting when budget runs low, and search queues don't adapt batch sizes as budget depletes.

## Scope

Three enhancements on top of the existing Prowlarr integration:

### 1. Visual Progress Bars on Dashboard

Replace the current "X of Y" text in the indexer health widget with progress bars.

- **Color thresholds**: green (<60%), gold (60-80%), red (>80%)
- **Data source**: existing `/api/dashboard/indexer-health` endpoint (no new API needed)
- **Fallback**: if no query_limit, show queries_used as count only (no bar)
- Pure UI change — the endpoint already returns `query_limit` and `queries_used`

### 2. Budget Alert Notifications

Fire a Discord notification when any indexer hits 80%+ usage.

- **New event toggle**: `budget_alert` added to `DEFAULT_EVENTS` (default: True)
- **New Discord method**: `send_budget_alert(indexer_name, queries_used, query_limit, percent_used)`
- **Trigger point**: inside the `/api/dashboard/indexer-health` endpoint after fetching data
- **Dedup**: track `_alerted_indexers: set[str]` at module level, keyed by `f"{indexer_name}:{limits_unit}"`. Reset the set when the budget period rolls over (hour/day). Only alert once per indexer per period.
- **Color**: red embed

### 3. Smart Batch Auto-Sizing

Enhance the existing rate limit integration to shrink batch sizes proportionally as budget depletes.

- **New field**: `budget_aware` boolean on `SearchQueue` model (default: True)
- **Logic**: In `SearchQueueManager.execute_queue()`, after `get_effective_limit()` returns the remaining budget:
  - If `budget_aware` is False or Prowlarr not configured: use existing behavior
  - If remaining budget < 20% of total limit: scale `max_items_per_run` proportionally
  - Formula: `effective_max = min(queue.max_items_per_run, remaining_budget)`
  - This already partially exists — `get_effective_limit()` returns the minimum remaining budget and the search execution caps at it. The enhancement is making this explicit and adding the toggle.
- **UI**: checkbox in queue creation/edit modal ("Adjust batch size based on indexer budget")

## Architecture

### Existing infrastructure (no changes needed)
- `ProwlarrClient.get_indexers()` — fetches limits
- `ProwlarrClient.get_indexer_stats()` — fetches usage
- `IndexerRateLimitService.get_effective_limit()` — computes remaining budget
- `/api/dashboard/indexer-health` — serves data to dashboard

### New code
- `DiscordNotificationService.send_budget_alert()` — new embed method
- `SearchQueue.budget_aware` — new boolean column (default True, auto-created on startup)
- Dashboard template: progress bar CSS + JS update
- Queue modal template: new checkbox
- Budget alert dedup module-level state

## Data Flow

```
Prowlarr API → ProwlarrClient → /api/dashboard/indexer-health
                                    ↓
                              Progress bars (UI)
                              Budget alert check → Discord notification

SearchQueue execution → IndexerRateLimitService → budget cap
                            ↓ (if budget_aware)
                       Proportional batch reduction
```

## Not Building
- Queue creation cost estimates
- Per-indexer time-to-exhaustion forecast
- Persistent indexer data storage (all from Prowlarr API)
- Grab limit tracking (only query limits for now)
