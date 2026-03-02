# Alpha Release Prep Design

**Date**: 2026-03-01
**Status**: Approved
**Goal**: Fix all bugs and polish found during hand-testing walkthrough, then proceed to code simplification, security review, and alpha release.

## Context

v0.5.1 is feature-complete. A hand walkthrough on Docker Desktop for Windows revealed critical bugs, major behavioral issues, UX polish needs, and infrastructure gaps that must be resolved before the alpha release (v1.0.0-alpha).

## Approach: Two Waves

- **Wave 1**: Critical bugs, major bugs, logging overhaul. Hand-validate before proceeding.
- **Wave 2**: UX polish, infrastructure. Hand-validate before proceeding.
- **Post-waves**: Code simplification, security review, alpha release with full documentation updates.

---

## Wave 1: Critical + Major Bug Fixes + Logging

### C1: Fix Database Locking

**Problem**: Library sync holds a long write lock. Every new DB connection runs `PRAGMA auto_vacuum = FULL` (requires write lock), causing cascading "database is locked" failures across sync-status polls, auth checks, and health checks. The entire app becomes unresponsive for 2+ minutes during sync.

**Fix**:

1. **Remove `PRAGMA auto_vacuum = FULL` from per-connection handler** (`database.py:112`). This PRAGMA only needs to be set once at database creation, not on every connection. Move to a one-time startup initialization. The other PRAGMAs (`journal_mode`, `synchronous`, `temp_store`, `secure_delete`) are connection-scoped or read-safe and stay.

2. **Add `PRAGMA busy_timeout = 5000`** in the per-connection handler. Tells SQLCipher to wait up to 5 seconds on lock contention instead of immediately failing.

3. **Make sync-status endpoint resilient to DB unavailability**. The endpoint reads an in-memory flag but currently requires a DB connection for auth. Catch DB errors gracefully in the auth dependency and return the in-memory sync state anyway (the user is already on an authenticated page).

**Files**: `src/splintarr/database.py`

### C2: Fix Raw JSON 401 Errors

**Problem**: When cookie auth fails (expired token, DB locked during auth check), the browser shows raw `{"detail":"Not authenticated"}` JSON instead of redirecting to login.

**Fix**:

1. **Global exception handler for 401s on HTML requests**: Check the request path or `Accept` header — if it's a browser page request (not AJAX), redirect to `/login?next={current_path}`.

2. **Global JS fetch interceptor in `base.html`**: Intercept 401 responses from AJAX calls and redirect to login, instead of silently failing.

**Files**: `src/splintarr/main.py`, `src/splintarr/templates/base.html`

### M1: Per-Episode Search Tracking

**Problem**: Queue searches the same episodes repeatedly across runs. Cooldown/scoring is at the series (LibraryItem) level, not episode level. No "already searched, no results" tracking per episode.

**Fix**:

1. **Schema change**: Add `last_searched_at` and `search_count` columns to the `LibraryEpisode` model.

2. **Scoring change**: In `search_queue.py` `compute_score`, deprioritize episodes where `last_searched_at` is recent and no grab was detected since. Recently-searched-no-result episodes get a score penalty.

3. **After search**: Update individual `LibraryEpisode.last_searched_at` when each episode is searched, not just the parent `LibraryItem`.

**Files**: `src/splintarr/models/library.py`, `src/splintarr/services/search_queue.py`

### M2: Season Pack Fallback to Individual Episodes

**Problem**: When season pack search is issued, all episode IDs for that season are marked as "handled" regardless of whether the search found results. Those episodes never get searched individually.

**Fix**: After `client.season_search()` returns, check the command result. If it indicates no results (or results can't be confirmed), don't add those episode IDs to `season_pack_handled_ids`. They fall through to individual episode search in step 8. Add a brief delay between season search and individual fallback to avoid rate-limiting.

**Files**: `src/splintarr/services/search_queue.py`

### M3: Onboarding "Sync Now" Link

**Problem**: Onboarding step says "Sync Library — Sync now" but the link just navigates to `/dashboard/library`. User must then find and click "Refresh Library" button.

**Fix**: Change the onboarding step action text to "Go to Library" and URL stays as `/dashboard/library`. The library empty state message already tells users to click "Refresh Library". This is clearer than magic auto-triggering.

**Files**: `src/splintarr/api/onboarding.py`

### M4: Sync Overlay with Progress and Error Reporting

**Problem**: Sync overlay shows generic "Syncing library..." with no progress indication. Errors are swallowed silently. The sync-status API only returns a boolean.

**Fix**:

1. **Backend**: Replace `_sync_in_progress` boolean with a module-level dict tracking: `syncing`, `current_instance`, `items_synced`, `total_instances`, `instances_done`, `errors[]`, `started_at`. Update as sync progresses. Expose via `/api/library/sync-status`.

2. **Frontend**: Update overlay to show real progress ("Syncing instance 1/3: Main Sonarr... 142 items"), elapsed time, and surface errors with a "Sync failed" state and actionable messages.

**Files**: `src/splintarr/api/library.py`, `src/splintarr/services/library_sync.py`, `src/splintarr/templates/dashboard/library.html`

### L1: Logging Overhaul — Clean JSONL with Size/Volume Controls

**Problem**: Logs are hard to read. Stack traces are inlined as massive single-line JSON strings (10KB+). Repetitive errors flood the log (dozens of identical DB lock traces). Volume limits are generous (150MB total).

**Fix**:

1. **Truncate stack traces**: Cap the `exception` field to the last 10 frames and 2KB total in non-debug logs. Full traces only in `debug.log`.

2. **Truncate long field values**: Add a structlog processor that caps any single field value to 1KB with a `[truncated]` marker.

3. **Deduplicate repeated errors**: Track recent error events; after 5 repeats within 30 seconds, log a summary ("suppressed N duplicate errors") instead of repeating.

4. **Volume controls**: Reduce `maxBytes` to 5MB (from 10MB), `backupCount` to 3 (from 5). Total max ~40MB across all log types. Add 4KB max line length safety net.

5. **Noise reduction**: DB lock errors during sync logged once at ERROR then suppressed. Health check poll failures during sync logged at DEBUG not ERROR.

**Files**: `src/splintarr/logging_config.py`

---

## Wave 2: UX Polish + Infrastructure

### U1: Setup Wizard Step Indicator

Replace full-text step labels with numbered circles (1-6). `title` attribute for tooltip on hover. Active step shows label below circle. CSS-only change.

**Files**: `src/splintarr/static/css/theme.css`, all `setup/*.html` templates

### U2: Welcome Page Key Features

Replace feature list with alpha-accurate features: Sonarr support (Radarr coming soon), search intelligence, season packs, Prowlarr integration, Discord notifications, exclusion lists, encrypted database. Update Getting Started to reflect 6-step wizard.

**Files**: `src/splintarr/templates/setup/welcome.html`

### U3: Setup Complete Tips

Replace outdated tips with actionable alpha-relevant ones: sync library, create small queue, use "recent" strategy, check history, set up Discord.

**Files**: `src/splintarr/templates/setup/complete.html`

### U4: Disable Radarr in Alpha

- Hide Radarr option from instance type dropdowns (setup + instances page)
- Server-side validation: reject `instance_type=radarr` with friendly message
- Note "Sonarr support (Radarr coming soon)" in welcome page and docs
- Keep all backend Radarr code intact

**Files**: `src/splintarr/templates/setup/instance.html`, `src/splintarr/templates/dashboard/instances.html`, `src/splintarr/api/search_queue.py` or instance creation endpoint, `src/splintarr/templates/setup/welcome.html`

### U5: Prowlarr URL Click-to-Copy

Add `copy-url` class and `title="Click to copy"` to Prowlarr URL `<code>` tags. Add click-to-copy JS handler (same pattern as instance setup).

**Files**: `src/splintarr/templates/setup/prowlarr.html`, `src/splintarr/templates/dashboard/settings.html`

### U6: Config Export Import Note

Add note below export button: "Config import will be available in a future release."

**Files**: `src/splintarr/templates/dashboard/settings.html`

### U7: Dashboard Section Reorder

Swap Indexer Health and Recent Search Activity sections so activity is above indexer health.

**Files**: `src/splintarr/templates/dashboard/index.html`

### U8: Edit Active Queue

- Add "Edit" button to queue cards
- Edit modal pre-populated with current settings, instance field disabled/locked
- Uses existing PATCH `/api/search-queues/{id}` endpoint

**Files**: `src/splintarr/templates/dashboard/search_queues.html`, `src/splintarr/api/search_queue.py`

### U9: Tooltip Explanations

Add `title` attributes to "X searched of Y eligible" text explaining: "Searched = items sent to Sonarr for search. Eligible = items matching queue filters."

**Files**: `src/splintarr/templates/dashboard/index.html`, `src/splintarr/templates/dashboard/search_history.html`, `src/splintarr/templates/dashboard/search_queue_detail.html`

### U10: Clickable Search History Entries

Make search execution rows in dashboard and history pages link to queue detail page for that execution's queue.

**Files**: `src/splintarr/templates/dashboard/index.html`, `src/splintarr/templates/dashboard/search_history.html`

### I1: Linux/macOS Setup Script

Create `setup.sh` equivalent to `setup-windows.ps1`: prereq checks, directory creation, secret generation, optional auto-start (`--auto-start` flag).

**Files**: `scripts/setup.sh` (new)

### I2: Alpha Platform Documentation

Add note to README, wiki, release notes: "Alpha hand-tested on Docker Desktop for Windows. Expected to work on Linux/macOS Docker but not verified."

**Files**: `README.md`, wiki pages, release notes

### I3: generate-secrets.sh Parity

Add database auto-delete on secret regeneration (matching `.ps1` behavior).

**Files**: `scripts/generate-secrets.sh`

---

## Post-Wave Steps

After both waves are hand-validated:

1. **Code simplification** — Clean pass to reduce duplication
2. **Security review** — Deep audit of entire codebase, issues/PRs for findings
3. **Alpha release** — Version bump, README, wiki, PRD, screenshots, GitHub release
