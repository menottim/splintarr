# v0.3.0 Search Intelligence — Design Document

**Date:** 2026-02-28
**Status:** Approved
**PRD Features:** #10 (Adaptive Search Prioritization), #11 (Search Cooldown Intelligence), #12 (Search Result Feedback Loop)

---

## Goal

Make searches smarter, not just scheduled. Score items by likelihood of success, apply age-aware cooldowns, and detect whether searches actually result in grabs.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Scoring data source | API response enriched with DB data | Always searches what *arr says is missing; our DB adds history |
| Persistence | All scoring/cooldown data in DB (LibraryItem columns) | Survives restarts; accumulates over time |
| Grab detection | Poll command status after 15-min delay | Direct, uses existing API; command_id already logged |
| Scoring approach | Unified scorer with strategy-aware weights | One function, less code, easier to tune |
| Cooldown config | Per-queue (adaptive or flat) | Each queue can have different behavior |
| Score visibility | Score + top factor in search log | Transparent without cluttering UI |
| Batch limit | Per-queue max_items_per_run (default 50) | Scoring only useful when selecting a subset |
| Fetch strategy | Fetch all wanted items, accept read cost | 20s for 5,000 items is fine for a background job |

---

## Data Model Changes

### LibraryItem — 4 new columns

```python
search_attempts = Column(Integer, default=0, nullable=False)
last_searched_at = Column(DateTime, nullable=True)
grabs_confirmed = Column(Integer, default=0, nullable=False)
last_grab_at = Column(DateTime, nullable=True)
```

### SearchQueue — 3 new fields

```python
cooldown_mode = Column(String(20), default="adaptive", nullable=False)  # 'adaptive' | 'flat'
cooldown_hours = Column(Integer, nullable=True)  # used when mode='flat'
max_items_per_run = Column(Integer, default=50, nullable=False)  # range 1-500
```

### Config — 1 new setting

```python
FEEDBACK_CHECK_DELAY_MINUTES: int = 15  # delay before polling command statuses
```

---

## Scoring Algorithm

### Factors

**Recency (0-40):** Based on air_date (Sonarr) or added date (Radarr).

| Item Age | Score |
|----------|-------|
| < 24 hours | 40 |
| < 7 days | 30 |
| < 30 days | 20 |
| < 1 year | 10 |
| > 1 year | 5 |
| Unknown date | 15 |

**Attempts (0-30):** Fewer search attempts = higher score (diminishing returns on re-searching).

| Attempts | Score |
|----------|-------|
| 0 (never searched) | 30 |
| 1-5 | 25 |
| 6-10 | 15 |
| 11-20 | 8 |
| 20+ | 2 |

**Staleness (0-30):** Time since last search. Items not searched recently get priority.

| Time Since Search | Score |
|-------------------|-------|
| Never searched | 30 |
| > 7 days | 25 |
| > 3 days | 20 |
| > 1 day | 15 |
| < 1 day | 5 |

### Strategy Weights

| Strategy | Recency Weight | Attempts Weight | Staleness Weight | Rationale |
|----------|---------------|-----------------|------------------|-----------|
| Missing | 1.5 | 0.8 | 0.7 | Fresh content is most findable |
| Cutoff Unmet | 0.7 | 0.8 | 1.5 | Spread searches over time |
| Recent | 2.0 | 0.5 | 0.5 | Heavily favor recent air dates |

**Final score** = Σ(factor × weight), normalized to 0-100.

### Score in Search Log

Each search_log entry gains two fields:

```python
{"item": "Show S01E05", "action": "EpisodeSearch", "score": 82, "score_reason": "recently aired", ...}
```

The `score_reason` is the factor with the highest weighted contribution.

---

## Tiered Cooldown

### Adaptive Mode (default)

Base cooldown determined by item age:

| Item Age | Base Cooldown |
|----------|--------------|
| < 24 hours | 6 hours |
| < 7 days | 12 hours |
| < 30 days | 24 hours |
| < 1 year | 72 hours |
| > 1 year | 7 days |

### Exponential Backoff

After each search with no grab confirmed, the effective cooldown doubles:

```
effective_cooldown = base_cooldown × 2^(consecutive_failures)
```

Where `consecutive_failures = search_attempts - grabs_confirmed`. Capped at 14 days.

### Cooldown Reset

Cooldown resets (next search allowed immediately) when:
- Content has a new air date more recent than `last_searched_at`
- A grab is confirmed (feedback loop)
- User manually triggers a search via the queue's "Search Now" button

### Flat Mode

When `cooldown_mode = 'flat'`, uses `cooldown_hours` as a fixed cooldown for all items regardless of age or history.

### Persistence

Cooldown checks query `LibraryItem.last_searched_at` from the database. The in-memory `_search_cooldowns` dict is removed entirely.

---

## Feedback Loop

### Trigger

After `execute_queue()` completes successfully with `searches_triggered > 0`, schedule a one-shot APScheduler job:

```python
scheduler.add_job(
    feedback_service.check_search_results,
    trigger="date",
    run_date=datetime.utcnow() + timedelta(minutes=settings.FEEDBACK_CHECK_DELAY_MINUTES),
    id=f"feedback_check_{history_id}",
    args=[history_id, instance_id],
)
```

### Check Process

1. Load `SearchHistory` by ID, parse `search_metadata` JSON
2. Extract entries with `action` = "EpisodeSearch" or "MoviesSearch" and a `command_id`
3. For each command_id:
   a. Call `get_command_status(command_id)` on the instance
   b. If status = "completed" and result = "successful":
      - For Sonarr: call `get_episodes(series_id)`, check if the specific episode now has `hasFile=True`
      - For Radarr: call `get_movies(movie_id)`, check `hasFile`
   c. If grab detected:
      - Increment `LibraryItem.grabs_confirmed`
      - Set `LibraryItem.last_grab_at = utcnow()`
      - Mark entry in search_metadata with `grab_confirmed: true`
4. Update `SearchHistory.search_metadata` with enriched entries
5. Log summary: `feedback_check_completed` with grab_count, checked_count

### Dashboard Metric

New stat on dashboard: **Grab Rate** = `total grabs_confirmed / total searches_triggered` across all history. Displayed as a percentage next to the existing "Searches Today" stat.

---

## Search Flow (Updated)

```
execute_queue(queue_id):
  1. Load queue + instance (existing)
  2. Mark in-progress (existing)
  3. Create history record (existing)
  4. _execute_strategy(queue, instance, db):
     a. Determine fetch_method, strategy_name (existing)
     b. Fetch ALL wanted items (paginated) — collect into single list
     c. Load exclusion keys (existing)
     d. Load scoring data: batch query LibraryItem for all external_ids
     e. Score each item using compute_score(record, library_item, strategy)
     f. Sort by score descending
     g. Apply exclusion filter (remove excluded items)
     h. Apply cooldown filter (remove items in cooldown)
     i. Truncate to max_items_per_run
     j. Search each remaining item:
        - Trigger search command
        - Update LibraryItem.search_attempts += 1, last_searched_at = now
        - Log score + score_reason in search_log entry
     k. Return results
  5. Mark completed, store search_metadata (existing)
  6. Discord notification (existing)
  7. Schedule feedback check (NEW)
```

---

## PR Structure

### PR 1: Data Model + Scoring Engine

- LibraryItem: 4 new columns
- SearchQueue: 3 new fields (cooldown_mode, cooldown_hours, max_items_per_run)
- Config: FEEDBACK_CHECK_DELAY_MINUTES
- `src/splintarr/services/scoring.py`: `compute_score()` function with factor calculators
- Unit tests for scoring (all factor combinations, strategy weights, edge cases)
- Schema updates for SearchQueue create/update

### PR 2: Search Loop Integration

- Refactor `_search_paginated_records` to: fetch all → score → sort → filter → search top N
- Replace in-memory cooldown with DB-backed tiered cooldown
- Update LibraryItem.search_attempts and last_searched_at after each search
- Add score and score_reason to search_log entries
- Unit tests for cooldown logic, integration tests for search flow

### PR 3: Feedback Loop Service

- `src/splintarr/services/feedback.py`: FeedbackCheckService
- Schedule feedback check job after search completion
- Poll command statuses, detect grabs, update LibraryItem
- Update search_metadata with grab_confirmed
- Unit tests for feedback service

### PR 4: UI Updates

- Queue detail page: show score + score_reason in search log entries
- Library detail page: show search stats (attempts, grabs, last searched, priority score)
- Create Queue modal: cooldown mode selector, max_items_per_run field
- Dashboard: grab rate metric
- Settings/config: feedback check delay

---

## Open Questions (Resolved)

| Question | Resolution |
|----------|------------|
| Score against API or local data? | API enriched with DB data |
| Persist cooldowns? | Yes, in DB on LibraryItem |
| Grab detection approach? | Poll command status after 15-min delay |
| Scoring architecture? | Unified scorer with strategy weights |
| Cooldown granularity? | Per-queue (adaptive or flat) |
| Score visibility? | Score + top factor in search log |
| Batch limits? | Per-queue max_items_per_run (default 50) |
| Fetch strategy? | Fetch all pages, accept read cost |
