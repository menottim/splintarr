# Feature 1: Sonarr/Radarr Sync & Library Overview — Design Document

**Date:** 2026-02-27
**PRD Reference:** docs/PRD-v0.2.md, Feature 1
**Status:** Draft

---

## Problem

Users can't see what's in their Sonarr/Radarr libraries from within Splintarr. They must switch between apps to understand what's missing, what's complete, and what's been searched. The dashboard shows aggregate search stats but no library context.

## Solution

A read-only local cache of series/movie data synced from connected instances, displayed as a browseable library with poster art, completion tracking, and a "missing content" view aggregated across all instances.

---

## Data Model

### `library_items` table

One row per series (Sonarr) or movie (Radarr) per instance.

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer PK | Auto-increment |
| `instance_id` | Integer FK → instances.id | Source instance (CASCADE delete) |
| `content_type` | Enum: series, movie | Sonarr = series, Radarr = movie |
| `external_id` | Integer | ID in the source instance |
| `title` | String(500) | Series or movie title |
| `year` | Integer, nullable | Release year |
| `status` | String(50), nullable | Series/movie status (continuing, ended, released, etc.) |
| `quality_profile` | String(100), nullable | Quality profile ID from instance |
| `episode_count` | Integer, default 0 | Total monitored episodes (Sonarr) or 1 (Radarr) |
| `episode_have` | Integer, default 0 | Downloaded episodes or 1 if file exists (Radarr) |
| `poster_path` | String(500), nullable | Relative path to cached poster: `{instance_id}/{content_type}/{external_id}.jpg` |
| `metadata_json` | Text, nullable | Truncated JSON from last sync for debugging |
| `last_synced_at` | DateTime, nullable | Last successful sync timestamp |
| `added_at` | DateTime, nullable | Date added in the *arr instance |
| `created_at` | DateTime | Row creation |
| `updated_at` | DateTime | Last update |

**Unique constraint:** `(instance_id, content_type, external_id)`

### `library_episodes` table (Sonarr only)

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer PK | Auto-increment |
| `library_item_id` | Integer FK → library_items.id | Parent series (CASCADE delete) |
| `season_number` | Integer | Season number |
| `episode_number` | Integer | Episode number within season |
| `title` | String(500), nullable | Episode title |
| `air_date` | DateTime, nullable | Original air date |
| `has_file` | Boolean, default False | Whether file is downloaded |
| `monitored` | Boolean, default True | Whether episode is monitored |
| `created_at` | DateTime | Row creation |
| `updated_at` | DateTime | Last update |

**Unique constraint:** `(library_item_id, season_number, episode_number)`

### Model Properties

`LibraryItem`:
- `completion_pct` → float (0.0–100.0)
- `is_complete` → bool
- `missing_count` → int

---

## Sync Architecture

### Service: `LibrarySyncService`

Singleton pattern matching `SearchScheduler`. Initialized with `db_session_factory`.

**Core method: `sync_instance(instance_id: int)`**
1. Decrypt API key
2. If Sonarr: fetch `/api/v3/series`, for each series: upsert `library_items`, fetch `/api/v3/episode?seriesId=N` and upsert `library_episodes`, download poster
3. If Radarr: fetch `/api/v3/movie`, for each movie: upsert `library_items`, download poster
4. Delete library_items not seen in this sync (handles items removed from *arr)
5. Per-item error handling — one failure doesn't abort the sync

**Poster download:**
- Source: Sonarr `/api/v3/mediacover/{id}/poster.jpg`, Radarr `/api/v3/mediacover/{id}/poster.jpg`
- Storage: `data/posters/{instance_id}/{content_type}/{external_id}.jpg`
- Skip re-download if file already exists (no force refresh in v1)
- Served via a dedicated FastAPI `StaticFiles` mount at `/posters`

**APScheduler integration:**
- Job ID: `"library_sync"` (single job for all instances)
- Trigger: `interval`, hours=`LIBRARY_SYNC_INTERVAL_HOURS` (default 6)
- Registered in `main.py` lifespan alongside the search scheduler

### Sonarr/Radarr API Endpoints Used

| Instance | Endpoint | Method | Purpose |
|----------|----------|--------|---------|
| Sonarr | `/api/v3/series` | GET | All series with stats |
| Sonarr | `/api/v3/episode?seriesId={id}` | GET | Episodes for a series |
| Sonarr | `/api/v3/mediacover/{id}/poster.jpg` | GET | Poster image |
| Radarr | `/api/v3/movie` | GET | All movies |
| Radarr | `/api/v3/mediacover/{id}/poster.jpg` | GET | Poster image |

---

## UI Design

### Navigation

Add "Library" to the sidebar between "Instances" and "Queues".

### Pages

**1. Library Overview (`/dashboard/library`)**
- Stats bar: Total items, percent complete, total missing
- Instance filter dropdown
- Content type tabs: All | Series | Movies
- Poster card grid (responsive, 4-6 columns)
- Each card: poster image, title, year, completion bar, instance badge
- Sort: alphabetical, completion %, recently added
- "Refresh Library" button (triggers sync for all instances)

**2. Missing Content (`/dashboard/library/missing`)**
- Filtered view of items where `episode_have < episode_count`
- Same grid layout as overview but pre-filtered
- Sorted by missing count descending

**3. Item Detail (`/dashboard/library/{item_id}`)**
- Large poster + title + metadata
- For series: episode grid grouped by season (green = have, red = missing)
- For movies: single status card (downloaded/missing, quality)
- Last searched date (JOIN to search_history)
- Link back to library overview

### JSON API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/library/sync` | POST | Trigger manual sync (returns 202) |
| `/api/library/stats` | GET | Aggregate stats (total, complete, missing) |
| `/api/library/items` | GET | Paginated items with filters (instance, type, status) |

---

## Configuration

Add to `Settings` in `config.py`:

```python
library_sync_interval_hours: int = Field(
    default=6,
    ge=1,
    le=168,
    description="Hours between automatic library syncs",
)
```

---

## PR Breakdown

### PR 1: Data Models and Model Registration

**Files:**
- Create `src/splintarr/models/library.py` — `LibraryItem` and `LibraryEpisode` models
- Update `src/splintarr/models/__init__.py` — export new models
- Update `src/splintarr/models/instance.py` — add `library_items` relationship
- Add `library_sync_interval_hours` to `src/splintarr/config.py`
- Write `tests/unit/test_library_models.py` — model creation, properties, constraints

**Why first:** Models are the foundation. Other PRs depend on them. No service or UI code yet.

### PR 2: Sync Service and Background Job

**Depends on:** PR 1

**Files:**
- Add `get_series()`, `get_episodes()`, `get_poster_bytes()` to `src/splintarr/services/sonarr.py`
- Add `get_movies()`, `get_poster_bytes()` to `src/splintarr/services/radarr.py`
- Create `src/splintarr/services/library_sync.py` — `LibrarySyncService`
- Update `src/splintarr/main.py` — register sync job in lifespan, mount `/posters` static dir
- Write `tests/unit/test_library_sync.py` — mock API clients, test upsert, poster caching

### PR 3: API Routes and Templates

**Depends on:** PR 2

**Files:**
- Create `src/splintarr/api/library.py` — 3 HTML routes + 3 JSON API routes
- Create `src/splintarr/templates/dashboard/library.html` — poster grid overview
- Create `src/splintarr/templates/dashboard/library_missing.html` — missing content filter
- Create `src/splintarr/templates/dashboard/library_detail.html` — item detail with episodes
- Update `src/splintarr/templates/base.html` — add Library nav item
- Update `src/splintarr/static/css/custom.css` — poster grid styles
- Write `tests/integration/test_library_api.py`

### PR 4: Dashboard Integration

**Depends on:** PR 3

**Files:**
- Update `src/splintarr/templates/dashboard/index.html` — add library stats card
- Add Quick Actions entry: "Browse Library"

---

## Open Questions Resolved

| Question | Decision |
|----------|----------|
| Poster storage | Local cache in `data/posters/` |
| Sync frequency | Default 6 hours, configurable |
| Episode-level detail | Yes, for Sonarr only (library_episodes table) |
| Quality profile display | Store ID for now, display as-is |
| Force poster refresh | Not in v1 — skip if file exists |

## Risks

- **Large libraries:** A user with 1000+ series could have slow initial sync. Mitigated by per-item error handling and progress logging.
- **Poster disk usage:** ~200KB per poster × 1000 items = ~200MB. Acceptable for homelab use.
- **Stale data:** 6-hour default means data could be up to 6 hours out of date. Manual refresh button and configurable interval mitigate this.
