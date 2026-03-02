# Alpha Release Prep Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix all critical/major bugs and UX issues found during hand-testing to prepare Splintarr for alpha release.

**Architecture:** Two-wave approach. Wave 1 fixes core bugs (DB locking, auth, search behavior, sync, logging). Wave 2 applies UX polish and infrastructure. Each wave is hand-validated before proceeding.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy + SQLCipher, structlog, Jinja2 templates, Pico CSS

**Test runner:** `.venv/bin/python -m pytest` (poetry is not on PATH)
**Linter:** `.venv/bin/ruff check src/`
**Type check:** `.venv/bin/python -m mypy src/`

---

## Wave 1: Critical + Major Bug Fixes + Logging

---

### Task 1: Fix Database Locking (C1)

**Files:**
- Modify: `src/splintarr/database.py:63-121` (set_sqlite_pragma)
- Modify: `src/splintarr/database.py:301-342` (init_db)
- Test: `tests/unit/test_database.py`

**Step 1: Add busy_timeout PRAGMA**

In `src/splintarr/database.py`, in `set_sqlite_pragma` (line 63), add `PRAGMA busy_timeout = 5000` after line 80 (after cursor creation):
```python
cursor.execute("PRAGMA busy_timeout = 5000")
```

**Step 2: Remove auto_vacuum from per-connection handler**

Remove lines 107-112 (the auto_vacuum block that checks for in-memory and runs `PRAGMA auto_vacuum = FULL`).

**Step 3: Add one-time auto_vacuum in init_db**

In `init_db()` (line 301), add before `Base.metadata.create_all()`:
```python
with engine.connect() as conn:
    conn.execute(text("PRAGMA auto_vacuum = FULL"))
    conn.commit()
```

**Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/test_database.py -v --no-cov`

**Step 5: Commit**

```
fix(database): resolve DB locking by removing per-connection auto_vacuum and adding busy_timeout
```

---

### Task 2: Make Sync Status Endpoint Resilient (C1 continued)

**Files:**
- Modify: `src/splintarr/api/library.py:397-405`

**Step 1: Make sync-status handle DB errors during sync**

Replace `api_library_sync_status` (lines 397-405). Remove the `Depends(get_current_user_from_cookie)` and `Depends(get_db)` parameters. Do a manual best-effort auth check that catches DB errors when sync is running:

```python
@router.get("/api/library/sync-status", include_in_schema=False)
@limiter.limit("60/minute")
async def api_library_sync_status(
    request: Request,
) -> JSONResponse:
    """Check whether a library sync is currently running."""
    try:
        db = next(get_db())
        try:
            get_current_user_from_cookie(request=request, db=db)
        except Exception:
            if not _sync_in_progress:
                raise
        finally:
            db.close()
    except Exception:
        if not _sync_in_progress:
            raise HTTPException(status_code=401, detail="Not authenticated")

    return JSONResponse(content={"syncing": _sync_in_progress})
```

**Step 2: Run tests**

Run: `.venv/bin/python -m pytest tests/ -k "library" -v --no-cov`

**Step 3: Commit**

```
fix(library): make sync-status endpoint resilient to DB lock during sync
```

---

### Task 3: Fix Raw JSON 401 Errors (C2)

**Files:**
- Modify: `src/splintarr/main.py:375-398` (http_exception_handler)
- Modify: `src/splintarr/templates/base.html`

**Step 1: Add 401 redirect for browser requests**

In `src/splintarr/main.py`, at the top of `http_exception_handler` (line 375), add before existing logic:

```python
if exc.status_code == 401:
    accept = request.headers.get("accept", "")
    is_browser = "text/html" in accept and "application/json" not in accept
    is_page_request = not request.url.path.startswith("/api/")
    if is_browser or is_page_request:
        from urllib.parse import quote
        next_url = quote(str(request.url.path), safe="")
        return RedirectResponse(
            url=f"/login?next={next_url}",
            status_code=status.HTTP_302_FOUND,
        )
```

**Step 2: Add global fetch 401 interceptor in base.html**

In `src/splintarr/templates/base.html`, add in the main script block:

```javascript
(function() {
    var originalFetch = window.fetch;
    window.fetch = function() {
        return originalFetch.apply(this, arguments).then(function(response) {
            if (response.status === 401) {
                window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname);
            }
            return response;
        });
    };
})();
```

**Step 3: Run tests**

Run: `.venv/bin/python -m pytest tests/ -k "auth" -v --no-cov`

**Step 4: Commit**

```
fix(auth): redirect to login on 401 instead of showing raw JSON
```

---

### Task 4: Per-Episode Search Tracking (M1)

**Files:**
- Modify: `src/splintarr/models/library.py:255-348` (LibraryEpisode)
- Modify: `src/splintarr/services/search_queue.py:526-580,668-752`

**Step 1: Add search tracking columns to LibraryEpisode**

In `src/splintarr/models/library.py`, add after line 318 (after `monitored` column):

```python
    # Search tracking (per-episode)
    search_attempts = Column(
        Integer,
        default=0,
        nullable=False,
        comment="Number of times this episode has been searched",
    )
    last_searched_at = Column(
        DateTime,
        nullable=True,
        comment="UTC timestamp of last search for this episode",
    )
```

Add a `record_search` method after `episode_code`:

```python
    def record_search(self) -> None:
        """Record a search attempt for this episode."""
        self.search_attempts = (self.search_attempts or 0) + 1
        self.last_searched_at = datetime.utcnow()
```

Ensure `from datetime import datetime` is in imports.

**Step 2: Load episode tracking in search loop**

In `src/splintarr/services/search_queue.py`, after `_load_library_items` call (around line 526), add:

```python
episode_tracking: dict[tuple[int, int, int], Any] = {}
if is_sonarr and library_items:
    from splintarr.models.library import LibraryEpisode
    item_ids = [li.id for li in library_items.values()]
    if item_ids:
        db_episodes = db.query(LibraryEpisode).filter(
            LibraryEpisode.library_item_id.in_(item_ids)
        ).all()
        for ep in db_episodes:
            if ep.library_item:
                episode_tracking[(ep.library_item.external_id, ep.season_number, ep.episode_number)] = ep
```

**Step 3: Add score penalty for recently searched episodes**

In the scoring loop (around line 579), after `compute_score`:

```python
score, reason = compute_score(record, library_item, strategy_name)
if is_sonarr:
    s_id = record.get("seriesId") or record.get("series", {}).get("id")
    s_num = record.get("seasonNumber")
    e_num = record.get("episodeNumber")
    if s_id and s_num is not None and e_num is not None:
        ep_rec = episode_tracking.get((s_id, s_num, e_num))
        if ep_rec and ep_rec.last_searched_at:
            hours = (datetime.utcnow() - ep_rec.last_searched_at).total_seconds() / 3600
            if hours < 24:
                penalty = 50.0 * (1.0 - hours / 24.0)
                score = max(0, score - penalty)
                reason += f" (ep searched {hours:.0f}h ago: -{penalty:.0f})"
```

**Step 4: Update per-episode tracking after search**

After a successful search (around line 712), add:

```python
if is_sonarr:
    s_id = record.get("seriesId") or record.get("series", {}).get("id")
    s_num = record.get("seasonNumber")
    e_num = record.get("episodeNumber")
    ep_rec = episode_tracking.get((s_id, s_num, e_num))
    if ep_rec:
        ep_rec.record_search()
```

**Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/ -v --no-cov`

**Step 6: Commit**

```
feat(search): add per-episode search tracking to prevent repeated searches
```

---

### Task 5: Season Pack Fallback (M2)

**Files:**
- Modify: `src/splintarr/services/search_queue.py:668-674`

**Step 1: Remove season-pack-handled skip**

In `src/splintarr/services/search_queue.py`, remove lines 672-674:

```python
                    # Skip items already handled by season pack searches
                    if item_id in season_pack_handled_ids:
                        continue
```

Replace with a comment:

```python
                    # Season pack search is an optimization; individual search
                    # serves as fallback if season pack didn't find results.
```

**Step 2: Run tests**

Run: `.venv/bin/python -m pytest tests/ -k "search_queue" -v --no-cov`

**Step 3: Commit**

```
fix(search): allow individual episode search as fallback after season pack
```

---

### Task 6: Fix Onboarding "Sync Now" (M3)

**Files:**
- Modify: `src/splintarr/api/onboarding.py:104`

**Step 1: Change action text**

Change line 104 from `"action": "Sync now"` to `"action": "Go to Library"`.

**Step 2: Commit**

```
fix(onboarding): change misleading "Sync now" to "Go to Library"
```

---

### Task 7: Sync Progress and Error Reporting (M4)

**Files:**
- Modify: `src/splintarr/api/library.py:56-80`
- Modify: `src/splintarr/services/library_sync.py:52-96`
- Modify: `src/splintarr/templates/dashboard/library.html:113-147`

**Step 1: Replace sync flag with progress dict**

In `src/splintarr/api/library.py`, replace line 56 (`_sync_in_progress = False`) with:

```python
_sync_in_progress = False
_sync_state: dict[str, Any] = {
    "syncing": False,
    "current_instance": None,
    "items_synced": 0,
    "total_instances": 0,
    "instances_done": 0,
    "errors": [],
    "started_at": None,
}
```

**Step 2: Update background sync task**

Replace `_run_sync_all_background` (lines 59-80) to update `_sync_state` and pass a progress callback to the sync service. See design doc for full implementation.

**Step 3: Add progress_callback to sync_all_instances**

In `src/splintarr/services/library_sync.py`, add `progress_callback` parameter to `sync_all_instances` and call it during the instance loop.

**Step 4: Update sync-status to return full state**

Ensure the sync-status endpoint (modified in Task 2) returns `_sync_state` dict.

**Step 5: Update sync overlay in library.html**

Replace the overlay JS (lines 113-147) with a version that shows progress text ("Instance 1/3: Main Sonarr... 142 items"), error display, and a reload button on completion with errors. Use safe DOM methods only (createElement, textContent, appendChild — no innerHTML).

**Step 6: Run tests**

Run: `.venv/bin/python -m pytest tests/ -k "library" -v --no-cov`

**Step 7: Commit**

```
feat(library): add sync progress reporting with instance tracking and error display
```

---

### Task 8: Logging Overhaul (L1)

**Files:**
- Modify: `src/splintarr/logging_config.py`

**Step 1: Add truncation processor**

Add `truncate_long_values` processor that caps field values to 1KB (2KB for `exception` field), appending `[truncated]`.

**Step 2: Add error deduplication processor**

Add `deduplicate_errors` processor that tracks recent error events and raises `structlog.DropEvent` after 5 repeats within 30 seconds (logging a summary on the 5th).

**Step 3: Add processors to shared chain**

Add `truncate_long_values` and `deduplicate_errors` to `shared_processors` list, after `censor_sensitive_data` and before `drop_color_message_key`.

**Step 4: Reduce rotation limits**

Change `_create_file_handler`: `maxBytes=5 * 1024 * 1024` (5MB), `backupCount=3`.

**Step 5: Update startup log message**

Update the rotation dict in `logging_configured` log to reflect new limits.

**Step 6: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/ -v --no-cov`

**Step 7: Commit**

```
feat(logging): add truncation, deduplication, and reduced volume for cleaner JSONL logs
```

---

## Wave 2: UX Polish + Infrastructure

---

### Task 9: Compact Setup Step Indicator (U1)

**Files:**
- Modify: `src/splintarr/static/css/theme.css:486-550`
- Modify: All `src/splintarr/templates/setup/*.html` (6 files)

**Step 1:** Replace `.setup-progress` CSS with compact numbered circles (2rem diameter, centered, no text). Update all 6 setup templates: remove text content from step spans, keep `data-step` for the number, add `title` attribute for tooltip.

**Step 2: Commit**

```
fix(ui): make setup progress indicator compact numbered circles
```

---

### Task 10: Update Welcome Page Content (U2)

**Files:**
- Modify: `src/splintarr/templates/setup/welcome.html:31-49`

**Step 1:** Replace Key Features with alpha-accurate list (Sonarr, search intelligence, season packs, Prowlarr, Discord, exclusions, encrypted DB). Update Getting Started to reflect 6-step wizard with Sonarr-only language.

**Step 2: Commit**

```
fix(ui): update welcome page features and getting started for alpha
```

---

### Task 11: Update Setup Complete Tips (U3)

**Files:**
- Modify: `src/splintarr/templates/setup/complete.html:55-61`

**Step 1:** Replace tips with: sync library, create small queue, use recent strategy, check search history, set up Discord.

**Step 2: Commit**

```
fix(ui): update setup complete tips for alpha features
```

---

### Task 12: Disable Radarr in Alpha (U4)

**Files:**
- Modify: `src/splintarr/templates/setup/instance.html:28-32`
- Modify: `src/splintarr/templates/dashboard/instances.html` (Add Instance modal)
- Modify: Instance creation API endpoint

**Step 1:** Remove Radarr option from dropdowns, add "Radarr coming in a future release" notes. Add server-side validation rejecting `instance_type=radarr`.

**Step 2: Commit**

```
feat(alpha): disable Radarr instance creation with future release note
```

---

### Task 13: Prowlarr URL Click-to-Copy (U5)

**Files:**
- Modify: `src/splintarr/templates/setup/prowlarr.html:34`
- Modify: `src/splintarr/templates/dashboard/settings.html:192`

**Step 1:** Add `class="copy-url" title="Click to copy"` to Prowlarr URL `<code>` tags. Add click-to-copy JS handler (same pattern as `setup/instance.html` lines 213-228).

**Step 2: Commit**

```
fix(ui): add click-to-copy for Prowlarr URL suggestions
```

---

### Task 14: Config Export Import Note (U6)

**Files:**
- Modify: `src/splintarr/templates/dashboard/settings.html:233`

**Step 1:** Add `<small>` note after export button: "Config import will be available in a future release."

**Step 2: Commit**

```
fix(ui): add config import coming soon note
```

---

### Task 15: Dashboard Section Reorder (U7)

**Files:**
- Modify: `src/splintarr/templates/dashboard/index.html:54-143`

**Step 1:** Swap the Indexer Health block (lines 54-78) and Recent Search Activity block (lines 81-143).

**Step 2: Commit**

```
fix(ui): move recent search activity above indexer health on dashboard
```

---

### Task 16: Edit Active Queue (U8)

**Files:**
- Modify: `src/splintarr/templates/dashboard/search_queues.html`
- Modify: `src/splintarr/api/search_queue.py` (verify PATCH handles all fields)

**Step 1:** Add "Edit" button to queue cards. Add edit dialog pre-populated with current values (instance disabled). JS fetches queue data, populates form, submits via PATCH. Uses safe DOM methods.

**Step 2: Commit**

```
feat(ui): add edit button and modal for active search queues
```

---

### Task 17: Tooltip Explanations (U9)

**Files:**
- Modify: `src/splintarr/templates/dashboard/index.html`
- Modify: `src/splintarr/templates/dashboard/search_history.html`
- Modify: `src/splintarr/templates/dashboard/search_queue_detail.html`

**Step 1:** Add `title` attributes to "X searched of Y eligible" text: "Searched: items sent to Sonarr for search. Eligible: items that matched queue filters."

**Step 2: Commit**

```
fix(ui): add tooltip explanations for searched/eligible counts
```

---

### Task 18: Clickable Search History Entries (U10)

**Files:**
- Modify: `src/splintarr/templates/dashboard/index.html`
- Modify: `src/splintarr/templates/dashboard/search_history.html`

**Step 1:** Make queue name in search entries a link to `/dashboard/search-queues/{queue_id}`. Apply to both server-rendered and JS-rendered rows.

**Step 2: Commit**

```
fix(ui): make search history entries clickable to queue detail
```

---

### Task 19: Linux/macOS Setup Script (I1)

**Files:**
- Create: `scripts/setup.sh`

**Step 1:** Create `setup.sh` mirroring `setup-windows.ps1`: prereq checks (docker, docker-compose, running), create data/ and secrets/ dirs, run generate-secrets.sh, optional --auto-start flag. Make executable.

**Step 2: Commit**

```
feat(infra): add Linux/macOS setup script
```

---

### Task 20: generate-secrets.sh Parity (I3)

**Files:**
- Modify: `scripts/generate-secrets.sh:108-134`

**Step 1:** After user confirms secret regeneration, add database auto-delete (matching .ps1 behavior):

```bash
DB_PATH="./data/splintarr.db"
if [[ -f "$DB_PATH" ]]; then
    info "Deleting old database (incompatible with new keys)..."
    rm -f "${DB_PATH}"* 2>/dev/null || true
    success "Old database deleted"
fi
```

**Step 2: Commit**

```
fix(scripts): add database auto-delete on secret regeneration
```

---

### Task 21: Final Lint and Type Check

**Step 1:** Run: `.venv/bin/ruff check src/ --fix`
**Step 2:** Run: `.venv/bin/python -m mypy src/`
**Step 3:** Run: `.venv/bin/python -m pytest tests/unit/ tests/integration/ -v`
**Step 4:** Fix any issues.
**Step 5:** Commit: `chore: fix lint and type errors from alpha prep changes`

---

## Post-Implementation

After both waves are hand-validated:
1. Code simplification (code-simplifier skill)
2. Security review (deep audit, issues/PRs)
3. Alpha release (version bump, README, wiki, PRD, screenshots)
