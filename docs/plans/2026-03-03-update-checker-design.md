# Update Checker — Design Document

**Date**: 2026-03-03
**Status**: Approved
**Target Release**: TBD

## Overview

Splintarr automatically checks for new releases on GitHub and displays a dismissible banner on the dashboard when an update is available. Users can dismiss the banner per-version and disable update checking entirely via the Settings page.

## Requirements

- Check GitHub Releases API every 24 hours via APScheduler background job
- Cache result in-memory (module-level dict, same pattern as `_sync_state` in library.py)
- Display a dropdown banner at the top of the dashboard when a newer version exists
- Banner is dismissible per-version: dismissing v1.2.0 hides it until v1.3.0 is released
- Users can disable update checking via a Settings page toggle
- Graceful failure: if GitHub is unreachable, fail silently and leave cache unchanged
- Skip draft and pre-release GitHub releases
- Run one check on app startup, then every 24 hours

## Architecture

```
APScheduler (every 24h)
    → services/update_checker.py
        → GET https://api.github.com/repos/menottim/splintarr/releases/latest
        → parse tag_name, html_url, name
        → store in _update_state (in-memory dict)

Dashboard render (GET /)
    → read _update_state via get_update_state()
    → compare current_version vs latest_version (packaging.version)
    → check user.dismissed_update_version
    → conditionally render banner
```

## Database Changes

Two nullable columns added to the `User` model:

```python
dismissed_update_version: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
update_check_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
```

Single Alembic migration.

## Service Layer

**File**: `services/update_checker.py`

- `_update_state: dict[str, Any]` — module-level cache
- `async check_for_updates() -> dict` — fetches GitHub API, updates cache
- `get_update_state() -> dict` — returns cached state (read-only)
- `is_update_available(current_version: str) -> bool` — semver comparison

**GitHub API details:**
- `httpx.AsyncClient` with 5-second timeout
- User-Agent: `Splintarr/{version}`
- No auth token (60 req/hour unauthenticated limit, we use 1/day)
- Skip releases where `draft == True` or `prerelease == True`

**Error handling:**
- Network errors → log warning, leave cache unchanged
- JSON parse errors → log error, clear cache
- Rate limit (403) → log warning, retry next cycle

## API Endpoints

**File**: `api/updates.py`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/updates/status` | Returns current update state |
| POST | `/api/updates/dismiss` | Sets `user.dismissed_update_version` |
| POST | `/api/updates/toggle` | Toggles `user.update_check_enabled` |

All require auth. Rate limited at 10/minute.

## Dashboard UI

Banner in `dashboard/index.html`, positioned after the search-running banner:

```html
{% if update_available %}
<div class="update-banner" id="updateBanner">
    <span>&#9650;</span>
    <strong>Update Available:</strong> v{{ latest_version }}
    <a href="{{ release_url }}" target="_blank" rel="noopener">View release notes</a>
    <button data-action="dismiss-update" aria-label="Dismiss">✕</button>
</div>
{% endif %}
```

**Styling**: Gold/accent background, full-width bar, slide-down animation, fade-out on dismiss. Consistent with search-running banner pattern.

**Settings page**: Add "Update Notifications" on/off toggle alongside existing Discord notification settings.

## Dismissal Logic

1. User sees banner for v1.2.0
2. User clicks dismiss → `POST /api/updates/dismiss` → `user.dismissed_update_version = "1.2.0"`
3. Next dashboard load: `latest_version (1.2.0) == dismissed_version (1.2.0)` → banner hidden
4. v1.3.0 released → next check updates cache → `latest_version (1.3.0) != dismissed_version (1.2.0)` → banner reappears

## Testing

**Unit tests** (`test_update_checker.py`):
- Mock httpx responses: success, network error, rate limit, pre-release skip, malformed JSON
- Version comparison: newer, same, older, pre-release, dev
- Cache state management

**Unit tests** (`test_updates_api.py`):
- All three endpoints return correct responses
- Auth required on all endpoints
- Dismiss persists on user, re-check with newer version reappears

**Integration tests**:
- Dashboard renders/hides banner based on update state and dismissal
- Settings toggle persists and affects banner visibility

## Approach Alternatives Considered

**Client-side fetch on dashboard load**: Adds 200-500ms latency, requires client-side rendering logic, GitHub rate limit risk. Rejected.

**WebSocket push**: Over-engineered for a once-per-day event. Would still need server-side cache fallback. Rejected.
