# Custom Strategy Filters — Design Document

**Date**: 2026-03-04
**Status**: Approved
**Target Release**: v1.2.0
**PRD Feature**: #20

## Overview

Implement the stubbed "Custom" search strategy with simple dropdown filters: year range, quality profile, series status. The custom strategy is the only strategy that can combine missing + cutoff unmet sources in a single queue (explicit exception to strategy isolation principle).

## Filter Schema

Stored as JSON in the existing `filters` TEXT column on SearchQueue:

```json
{
  "sources": ["missing", "cutoff_unmet"],
  "year_min": 2020,
  "year_max": null,
  "quality_profiles": ["Ultra-HD", "HD-1080p"],
  "statuses": ["continuing", "ended"]
}
```

**Rules:**
- `sources` — required, at least one of `["missing", "cutoff_unmet"]`
- `year_min` / `year_max` — optional integers, null = no bound
- `quality_profiles` — optional list of strings, empty = all profiles
- `statuses` — optional list of strings, empty = all statuses (values: `continuing`, `ended`, `upcoming`, `deleted`)

Validated via a `CustomFilterConfig` Pydantic model in `schemas/search.py`.

## Execution Pipeline

The custom strategy replaces its stub implementation:

1. Parse `queue.filters` JSON into `CustomFilterConfig`
2. Determine sources from `filters.sources`
3. For each source:
   - `"missing"` → call `get_wanted_missing()` (paginated)
   - `"cutoff_unmet"` → call `get_wanted_cutoff()` (paginated)
4. Combine results, deduplicate by `(series_id, episode_id)` — missing wins on conflict
5. Load LibraryItem records for all series
6. Apply custom filters against LibraryItem data:
   - `year_min` / `year_max` → check `library_item.year`
   - `quality_profiles` → check `library_item.quality_profile in list`
   - `statuses` → check `library_item.status in list`
7. Feed filtered records into existing pipeline (exclusion → cooldown → score → sort → batch → execute)

**Scoring** uses `"custom"` as strategy name. Treated same as missing for now.

**Preview/dry-run** works automatically — same pipeline.

## UI — Queue Creation & Edit

When "Custom" is selected in the strategy dropdown, a filter section appears:

- **Search Sources** — checkboxes for missing and cutoff_unmet (at least one required)
- **Year Range** — two optional number inputs (min, max)
- **Series Status** — checkboxes for continuing, ended, upcoming (default: all checked)
- **Quality Profile** — checkboxes populated from library data via new API endpoint

Filter section hidden for other strategies. Edit mode pre-populates from existing filters JSON.

Quality profiles populated via `GET /api/instances/{id}/quality-profiles` which queries:
```sql
SELECT DISTINCT quality_profile FROM library_items WHERE instance_id = :id
```

If library not synced, shows hint: "Sync your library first to see quality profiles."

## API Changes

**New endpoint:**
- `GET /api/instances/{id}/quality-profiles` — returns distinct profile names for instance

**Modified schemas:**
- `SearchQueueCreate` / `SearchQueueUpdate` — `filters` field validated via `CustomFilterConfig` when `strategy == "custom"`, must be null otherwise

## Testing

**Unit tests:**
- Filter logic: year range, quality profile, status, combined, deduplication, invalid config
- Execution pipeline: single source, both sources, filters applied before scoring, preview respects filters
- Quality profiles API: returns profiles, empty list, auth required, ownership enforced

**Integration tests:**
- Queue create/edit with custom strategy saves/updates filters correctly
- Strategy validation (custom requires filters, others reject filters)

## Approach Alternatives Considered

**Filter as separate service**: Over-engineered. PRD only mentions custom strategy. YAGNI.

**Database-level filtering**: LibraryItems don't know episode-level missing/cutoff status — that data only comes from Sonarr wanted APIs. Would need cross-referencing, adding complexity.
