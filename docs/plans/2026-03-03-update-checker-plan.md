# Update Checker Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Automatically check GitHub for new Splintarr releases and display a dismissible banner on the dashboard.

**Architecture:** APScheduler background job checks GitHub Releases API every 24 hours, caches result in a module-level dict. Dashboard handler reads the cache and renders a banner when a newer version exists. Users dismiss per-version (stored on User model) and can disable checking via Settings.

**Tech Stack:** httpx (GitHub API), APScheduler (scheduling), packaging.version (semver comparison), SQLAlchemy (User model columns), Jinja2 (banner template)

---

### Task 1: Add User Model Columns

**Files:**
- Modify: `src/splintarr/models/user.py:104` (after totp_last_used_counter)

**Step 1: Add columns to User model**

In `src/splintarr/models/user.py`, after the TOTP section (line 104) and before the Timestamps section (line 106), add:

```python
    # Update notifications
    dismissed_update_version = Column(
        String(32),
        nullable=True,
        comment="Version string dismissed by user (e.g. '1.2.0')",
    )
    update_check_enabled = Column(
        Boolean,
        default=True,
        nullable=False,
        comment="Whether automatic update checking is enabled",
    )
```

**Step 2: Create Alembic migration**

Run: `.venv/bin/python -m alembic revision --autogenerate -m "Add update check fields to User model"`

Review the generated migration to confirm it adds `dismissed_update_version` (String, nullable) and `update_check_enabled` (Boolean, default True) to `users` table.

**Step 3: Commit**

```bash
git add src/splintarr/models/user.py alembic/versions/
git commit -m "feat: add update check columns to User model"
```

---

### Task 2: Update Checker Service — Tests

**Files:**
- Create: `tests/unit/test_update_checker.py`

**Step 1: Write failing tests for the service**

```python
"""Tests for update checker service."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from splintarr.services.update_checker import (
    _update_state,
    check_for_updates,
    get_update_state,
    is_update_available,
)


class TestIsUpdateAvailable:
    """Version comparison tests."""

    def test_newer_version_available(self):
        assert is_update_available("1.0.0", "1.1.0") is True

    def test_same_version(self):
        assert is_update_available("1.1.0", "1.1.0") is False

    def test_older_version(self):
        assert is_update_available("1.2.0", "1.1.0") is False

    def test_major_version_bump(self):
        assert is_update_available("1.9.9", "2.0.0") is True

    def test_dev_version(self):
        assert is_update_available("dev", "1.0.0") is False

    def test_patch_version(self):
        assert is_update_available("1.1.0", "1.1.1") is True


class TestGetUpdateState:
    """Cache read tests."""

    def test_returns_empty_when_no_check(self):
        state = get_update_state()
        assert isinstance(state, dict)


class TestCheckForUpdates:
    """GitHub API integration tests (mocked)."""

    @pytest.mark.asyncio
    async def test_success(self):
        mock_response = httpx.Response(
            200,
            json={
                "tag_name": "v2.0.0",
                "html_url": "https://github.com/menottim/splintarr/releases/tag/v2.0.0",
                "name": "v2.0.0 — Big Release",
                "draft": False,
                "prerelease": False,
            },
            request=httpx.Request("GET", "https://api.github.com/test"),
        )
        with patch("splintarr.services.update_checker.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await check_for_updates()

        assert result["latest_version"] == "2.0.0"
        assert result["release_url"] == "https://github.com/menottim/splintarr/releases/tag/v2.0.0"
        assert result["release_name"] == "v2.0.0 — Big Release"

    @pytest.mark.asyncio
    async def test_network_error_returns_empty(self):
        with patch("splintarr.services.update_checker.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.get = AsyncMock(side_effect=httpx.ConnectError("timeout"))

            result = await check_for_updates()

        assert result == {} or result.get("latest_version") is None

    @pytest.mark.asyncio
    async def test_skips_prerelease(self):
        mock_response = httpx.Response(
            200,
            json={
                "tag_name": "v2.0.0-beta",
                "html_url": "https://github.com/test",
                "name": "Beta",
                "draft": False,
                "prerelease": True,
            },
            request=httpx.Request("GET", "https://api.github.com/test"),
        )
        with patch("splintarr.services.update_checker.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await check_for_updates()

        # Should not report a prerelease as available
        assert result.get("latest_version") is None or result == {}

    @pytest.mark.asyncio
    async def test_skips_draft(self):
        mock_response = httpx.Response(
            200,
            json={
                "tag_name": "v2.0.0",
                "html_url": "https://github.com/test",
                "name": "Draft",
                "draft": True,
                "prerelease": False,
            },
            request=httpx.Request("GET", "https://api.github.com/test"),
        )
        with patch("splintarr.services.update_checker.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await check_for_updates()

        assert result.get("latest_version") is None or result == {}

    @pytest.mark.asyncio
    async def test_rate_limit_returns_empty(self):
        mock_response = httpx.Response(
            403,
            json={"message": "API rate limit exceeded"},
            request=httpx.Request("GET", "https://api.github.com/test"),
        )
        with patch("splintarr.services.update_checker.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.get = AsyncMock(return_value=mock_response)

            result = await check_for_updates()

        assert result == {} or result.get("latest_version") is None
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_update_checker.py -v --no-cov`
Expected: ImportError — `update_checker` module does not exist yet.

**Step 3: Commit**

```bash
git add tests/unit/test_update_checker.py
git commit -m "test: add update checker service tests (red)"
```

---

### Task 3: Update Checker Service — Implementation

**Files:**
- Create: `src/splintarr/services/update_checker.py`

**Step 1: Implement the service**

```python
"""
Update Checker Service for Splintarr.

Periodically checks GitHub Releases API for new versions and caches the result
in-memory. The dashboard reads this cache to display an update banner.
"""

from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from packaging.version import InvalidVersion, Version

from splintarr import __version__

logger = structlog.get_logger()

GITHUB_RELEASES_URL = "https://api.github.com/repos/menottim/splintarr/releases/latest"
REQUEST_TIMEOUT = 5.0

# Module-level cache (same pattern as _sync_state in api/library.py)
_update_state: dict[str, Any] = {}


def is_update_available(current: str, latest: str) -> bool:
    """Compare two version strings. Returns True if latest > current."""
    try:
        return Version(latest) > Version(current)
    except InvalidVersion:
        logger.warning("update_check_version_parse_failed", current=current, latest=latest)
        return False


def get_update_state() -> dict[str, Any]:
    """Return cached update state (read-only)."""
    return dict(_update_state)


async def check_for_updates() -> dict[str, Any]:
    """
    Fetch latest release from GitHub API and update the cache.

    Returns the update state dict. On error, returns empty dict and
    leaves existing cache unchanged (stale data > no data).
    """
    global _update_state
    logger.info("update_check_started")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                GITHUB_RELEASES_URL,
                headers={
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": f"Splintarr/{__version__}",
                },
                timeout=REQUEST_TIMEOUT,
                follow_redirects=True,
            )

        if response.status_code == 403:
            logger.warning("update_check_rate_limited")
            return {}

        if response.status_code != 200:
            logger.warning("update_check_http_error", status_code=response.status_code)
            return {}

        data = response.json()

        # Skip drafts and pre-releases
        if data.get("draft") or data.get("prerelease"):
            logger.debug("update_check_skipped_prerelease", tag=data.get("tag_name"))
            return {}

        tag = data.get("tag_name", "")
        latest_version = tag.lstrip("v")

        _update_state = {
            "latest_version": latest_version,
            "release_url": data.get("html_url", ""),
            "release_name": data.get("name", ""),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            "update_check_completed",
            current_version=__version__,
            latest_version=latest_version,
            update_available=is_update_available(__version__, latest_version),
        )

        return dict(_update_state)

    except httpx.ConnectError:
        logger.warning("update_check_network_error", error="connection failed")
        return {}
    except httpx.TimeoutException:
        logger.warning("update_check_timeout")
        return {}
    except Exception as e:
        logger.error("update_check_failed", error=str(e))
        _update_state.clear()
        return {}
```

**Step 2: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_update_checker.py -v --no-cov`
Expected: All tests PASS.

**Step 3: Commit**

```bash
git add src/splintarr/services/update_checker.py
git commit -m "feat: add update checker service with GitHub API integration"
```

---

### Task 4: API Endpoints — Tests

**Files:**
- Create: `tests/unit/test_updates_api.py`

**Step 1: Write failing tests for the API endpoints**

```python
"""Tests for update checker API endpoints."""

from unittest.mock import patch

import pytest
from starlette.testclient import TestClient


class TestUpdateStatus:
    """GET /api/updates/status tests."""

    def test_returns_state(self, client: TestClient, auth_headers: dict):
        with patch("splintarr.api.updates.get_update_state", return_value={
            "latest_version": "2.0.0",
            "release_url": "https://github.com/menottim/splintarr/releases/tag/v2.0.0",
            "release_name": "v2.0.0",
            "checked_at": "2026-03-03T00:00:00+00:00",
        }):
            response = client.get("/api/updates/status", cookies=auth_headers)
        assert response.status_code == 200
        assert response.json()["latest_version"] == "2.0.0"

    def test_requires_auth(self, client: TestClient):
        response = client.get("/api/updates/status")
        assert response.status_code in (401, 403, 307)


class TestUpdateDismiss:
    """POST /api/updates/dismiss tests."""

    def test_dismiss_sets_version(self, client: TestClient, auth_headers: dict, db_session):
        with patch("splintarr.api.updates.get_update_state", return_value={
            "latest_version": "2.0.0",
        }):
            response = client.post("/api/updates/dismiss", cookies=auth_headers)
        assert response.status_code == 200

    def test_requires_auth(self, client: TestClient):
        response = client.post("/api/updates/dismiss")
        assert response.status_code in (401, 403, 307)


class TestUpdateToggle:
    """POST /api/updates/toggle tests."""

    def test_toggle_disables(self, client: TestClient, auth_headers: dict, db_session):
        response = client.post("/api/updates/toggle", cookies=auth_headers)
        assert response.status_code == 200

    def test_requires_auth(self, client: TestClient):
        response = client.post("/api/updates/toggle")
        assert response.status_code in (401, 403, 307)
```

Note: The `auth_headers` and `db_session` fixtures must match whatever pattern the existing test suite uses. Check `conftest.py` for the exact fixture names and adapt. These tests will need a logged-in user — follow the same pattern as `tests/unit/test_dashboard_stats.py` for user creation and auth cookie setup.

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_updates_api.py -v --no-cov`
Expected: ImportError — `api.updates` does not exist yet.

**Step 3: Commit**

```bash
git add tests/unit/test_updates_api.py
git commit -m "test: add update checker API endpoint tests (red)"
```

---

### Task 5: API Endpoints — Implementation

**Files:**
- Create: `src/splintarr/api/updates.py`
- Modify: `src/splintarr/main.py:316-327` (add router)

**Step 1: Create the updates router**

```python
"""
Update checker API endpoints.

Provides endpoints for checking update status, dismissing update notifications,
and toggling update checking.
"""

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from splintarr.core.auth import get_current_user_from_cookie
from splintarr.database import get_db
from splintarr.models.user import User
from splintarr.services.update_checker import get_update_state, is_update_available
from splintarr import __version__

logger = structlog.get_logger()
limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/api/updates", tags=["updates"])


@router.get("/status")
@limiter.limit("10/minute")
async def update_status(
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie),
) -> JSONResponse:
    """Return current update check state."""
    state = get_update_state()
    latest = state.get("latest_version")
    return JSONResponse(content={
        **state,
        "current_version": __version__,
        "update_available": is_update_available(__version__, latest) if latest else False,
    })


@router.post("/dismiss")
@limiter.limit("10/minute")
async def dismiss_update(
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Dismiss update notification for the current latest version."""
    state = get_update_state()
    latest = state.get("latest_version")
    if latest:
        current_user.dismissed_update_version = latest
        db.commit()
        logger.debug("update_notification_dismissed", user_id=current_user.id, version=latest)
    return JSONResponse(content={"dismissed": latest})


@router.post("/toggle")
@limiter.limit("10/minute")
async def toggle_update_check(
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Toggle automatic update checking on/off."""
    current_user.update_check_enabled = not current_user.update_check_enabled
    db.commit()
    logger.info(
        "update_check_toggled",
        user_id=current_user.id,
        enabled=current_user.update_check_enabled,
    )
    return JSONResponse(content={"enabled": current_user.update_check_enabled})
```

**Step 2: Register the router in main.py**

In `src/splintarr/main.py`, add import at top with other API imports:

```python
from splintarr.api import updates
```

Then after line 327 (`app.include_router(ws.router)`), add:

```python
app.include_router(updates.router)
```

**Step 3: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_updates_api.py -v --no-cov`
Expected: All tests PASS (may need fixture adjustments — see note in Task 4).

**Step 4: Commit**

```bash
git add src/splintarr/api/updates.py src/splintarr/main.py
git commit -m "feat: add update checker API endpoints"
```

---

### Task 6: Schedule Background Job

**Files:**
- Modify: `src/splintarr/main.py:96-112` (lifespan function, after scheduler start)

**Step 1: Add update check to lifespan startup**

In the `lifespan` function in `main.py`, after the library sync service initialization (after line 111) and before the WebSocket wiring (line 113), add:

```python
        # Start update checker (initial check + schedule recurring)
        try:
            from splintarr.services.update_checker import check_for_updates

            await check_for_updates()
            logger.info("update_checker_initial_check_completed")

            # Schedule recurring check every 24 hours
            from splintarr.services.scheduler import _scheduler

            if _scheduler and _scheduler.running:
                _scheduler.add_job(
                    check_for_updates,
                    "interval",
                    hours=24,
                    id="update_checker",
                    name="Update Checker",
                    replace_existing=True,
                )
                logger.info("update_checker_scheduled", interval_hours=24)
        except Exception as e:
            logger.error("update_checker_start_failed", error=str(e))
            # Don't fail startup if update checker fails
```

Note: Check if `_scheduler` is exported from `scheduler.py`. If the scheduler is accessed differently (e.g., via a `get_scheduler()` function or a class method), adapt accordingly. The key pattern is: initial check on startup, then schedule via APScheduler interval job.

**Step 2: Test startup manually**

Run: `.venv/bin/python -m pytest tests/unit/test_update_checker.py tests/unit/test_updates_api.py -v --no-cov`
Expected: All tests still pass. The scheduler integration will be tested via manual Docker run.

**Step 3: Commit**

```bash
git add src/splintarr/main.py
git commit -m "feat: schedule update checker on startup with 24h interval"
```

---

### Task 7: Dashboard Banner — Template & CSS

**Files:**
- Modify: `src/splintarr/templates/dashboard/index.html:50-57` (before search running banner)
- Modify: `src/splintarr/static/css/custom.css:263` (after demo banner styles)
- Modify: `src/splintarr/api/dashboard.py:693-746` (dashboard_index handler — add update context)

**Step 1: Add update context to dashboard handler**

In `src/splintarr/api/dashboard.py`, in the `dashboard_index` function, add before the `return templates.TemplateResponse(...)` at line 732:

```python
    # Update checker
    from splintarr.services.update_checker import get_update_state, is_update_available
    from splintarr import __version__

    update_state = get_update_state()
    latest = update_state.get("latest_version")
    update_available = (
        latest
        and is_update_available(__version__, latest)
        and current_user.dismissed_update_version != latest
        and current_user.update_check_enabled
    )
```

Then add to the template context dict (inside the `TemplateResponse` call):

```python
            "update_available": update_available,
            "update_latest_version": latest,
            "update_release_url": update_state.get("release_url", ""),
            "update_release_name": update_state.get("release_name", ""),
```

**Step 2: Add banner to dashboard template**

In `src/splintarr/templates/dashboard/index.html`, after the statistics grid (line 49, after `</div>`) and before the search running banner (line 51), add:

```html
<!-- Update Available Banner -->
{% if update_available %}
<div class="update-banner" id="updateBanner">
    <span style="font-size: 1.1rem;">&#9650;</span>
    <span>
        <strong>Update Available:</strong> v{{ update_latest_version }}
        {% if update_release_name %}<small style="opacity: 0.8;"> &mdash; {{ update_release_name }}</small>{% endif %}
    </span>
    <span style="flex: 1;"></span>
    <a href="{{ update_release_url }}" target="_blank" rel="noopener" style="color: inherit; font-weight: 500;">View release notes</a>
    <button class="update-banner-dismiss" id="updateBannerDismiss" aria-label="Dismiss" title="Dismiss">&times;</button>
</div>
{% endif %}
```

**Step 3: Add CSS styles**

In `src/splintarr/static/css/custom.css`, after the search-running-banner styles (after line 284), add:

```css
/* Update available banner (dashboard) */
.update-banner {
    background: rgba(212, 160, 23, 0.15);
    border: 1px solid rgba(212, 160, 23, 0.40);
    border-radius: var(--border-radius);
    padding: 0.5rem 1rem;
    margin-bottom: 1.25rem;
    display: flex;
    align-items: center;
    gap: 0.75rem;
    font-size: 0.875rem;
    color: var(--brand-primary);
    animation: slideDown 0.3s ease-out;
}

.update-banner a:hover {
    text-decoration: underline;
}

.update-banner-dismiss {
    background: none;
    border: none;
    color: var(--brand-primary);
    cursor: pointer;
    font-size: 1.25rem;
    padding: 0 0.25rem;
    line-height: 1;
    opacity: 0.7;
    margin: 0;
    width: auto;
}

.update-banner-dismiss:hover {
    opacity: 1;
}

@keyframes slideDown {
    from {
        opacity: 0;
        transform: translateY(-0.5rem);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}
```

**Step 4: Add dismiss JavaScript**

In `src/splintarr/templates/dashboard/index.html`, in the existing `<script>` block at the bottom (find the block with `nonce="{{ request.state.csp_nonce }}"`), add:

```javascript
// Update banner dismiss
(function() {
    var btn = document.getElementById('updateBannerDismiss');
    if (btn) btn.addEventListener('click', async function() {
        var banner = document.getElementById('updateBanner');
        banner.style.opacity = '0';
        banner.style.transition = 'opacity 0.3s';
        setTimeout(function() { banner.style.display = 'none'; }, 300);
        try {
            await fetch('/api/updates/dismiss', { method: 'POST' });
        } catch (e) {
            // Silent fail — banner is already hidden client-side
        }
    });
})();
```

**Step 5: Run full test suite for regressions**

Run: `.venv/bin/python -m pytest tests/unit/ -v --no-cov`
Expected: No regressions.

**Step 6: Commit**

```bash
git add src/splintarr/api/dashboard.py src/splintarr/templates/dashboard/index.html src/splintarr/static/css/custom.css
git commit -m "feat: add update available banner to dashboard"
```

---

### Task 8: Settings Page Toggle

**Files:**
- Modify: `src/splintarr/templates/dashboard/settings.html:226-228` (after Prowlarr, before System)
- Modify: `src/splintarr/api/dashboard.py:1081-1096` (settings handler — add update_check_enabled to context)

**Step 1: Add update_check_enabled to settings context**

In the `dashboard_settings` handler (line 1081), add to the template context:

```python
            "update_check_enabled": current_user.update_check_enabled,
```

**Step 2: Add toggle section to settings template**

In `src/splintarr/templates/dashboard/settings.html`, after the Prowlarr `</details>` (line 226) and before the System `<details>` (line 228), add:

```html
<!-- Update Notifications -->
<details>
    <summary><strong>Update Notifications</strong></summary>
    <article>
        <p>Splintarr can automatically check GitHub for new releases and show a banner on the dashboard when an update is available.</p>

        <label>
            <input type="checkbox" id="updateCheckEnabled" {% if update_check_enabled %}checked{% endif %}>
            Check for updates automatically
        </label>
        <small>Checks once every 24 hours. No data is sent — only a read from GitHub's public API.</small>

        <div style="margin-top: 1rem;">
            <button type="button" id="checkNowBtn" class="secondary">Check Now</button>
            <small id="updateCheckStatus" style="display: none; margin-left: 0.5rem;"></small>
        </div>
    </article>
</details>
```

**Step 3: Add JavaScript for toggle and check-now**

In the `{% block extra_scripts %}` section of `settings.html`, add:

```javascript
// Update check toggle
document.getElementById('updateCheckEnabled').addEventListener('change', async function() {
    try {
        const response = await fetch('/api/updates/toggle', { method: 'POST' });
        const data = await response.json();
        Splintarr.showNotification(
            data.enabled ? 'Update checks enabled' : 'Update checks disabled',
            'success'
        );
    } catch (e) {
        Splintarr.showNotification('Failed to toggle update checks');
    }
});

// Check now button
document.getElementById('checkNowBtn').addEventListener('click', async function() {
    var status = document.getElementById('updateCheckStatus');
    var btn = this;
    btn.disabled = true;
    btn.setAttribute('aria-busy', 'true');
    status.style.display = 'none';

    try {
        const response = await fetch('/api/updates/status');
        const data = await response.json();
        status.style.display = 'inline';
        if (data.update_available) {
            status.textContent = 'Update available: v' + data.latest_version;
            status.style.color = 'var(--brand-primary)';
        } else {
            status.textContent = 'You are running the latest version.';
            status.style.color = 'var(--ins-color)';
        }
    } catch (e) {
        status.style.display = 'inline';
        status.textContent = 'Check failed — GitHub may be unreachable.';
        status.style.color = 'var(--del-color)';
    } finally {
        btn.disabled = false;
        btn.removeAttribute('aria-busy');
    }
});
```

**Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/ -v --no-cov`
Expected: All pass.

**Step 5: Commit**

```bash
git add src/splintarr/templates/dashboard/settings.html src/splintarr/api/dashboard.py
git commit -m "feat: add update check toggle to settings page"
```

---

### Task 9: Integration Tests

**Files:**
- Create: `tests/integration/test_update_banner.py`

**Step 1: Write integration tests**

```python
"""Integration tests for update checker banner on dashboard."""

from unittest.mock import patch

import pytest


class TestUpdateBannerIntegration:
    """Test banner visibility on dashboard."""

    def test_banner_shown_when_update_available(self, client, auth_headers, db_session):
        with patch("splintarr.api.dashboard.get_update_state", return_value={
            "latest_version": "99.0.0",
            "release_url": "https://github.com/menottim/splintarr/releases/tag/v99.0.0",
            "release_name": "v99.0.0",
        }), patch("splintarr.api.dashboard.is_update_available", return_value=True):
            response = client.get("/dashboard", cookies=auth_headers)
        assert response.status_code == 200
        assert "Update Available" in response.text
        assert "v99.0.0" in response.text

    def test_banner_hidden_when_up_to_date(self, client, auth_headers, db_session):
        with patch("splintarr.api.dashboard.get_update_state", return_value={
            "latest_version": "1.1.0",
        }), patch("splintarr.api.dashboard.is_update_available", return_value=False):
            response = client.get("/dashboard", cookies=auth_headers)
        assert response.status_code == 200
        assert "Update Available" not in response.text

    def test_banner_hidden_when_dismissed(self, client, auth_headers, db_session, user):
        user.dismissed_update_version = "99.0.0"
        db_session.commit()
        with patch("splintarr.api.dashboard.get_update_state", return_value={
            "latest_version": "99.0.0",
        }):
            response = client.get("/dashboard", cookies=auth_headers)
        assert response.status_code == 200
        assert "Update Available" not in response.text

    def test_banner_hidden_when_check_disabled(self, client, auth_headers, db_session, user):
        user.update_check_enabled = False
        db_session.commit()
        with patch("splintarr.api.dashboard.get_update_state", return_value={
            "latest_version": "99.0.0",
        }), patch("splintarr.api.dashboard.is_update_available", return_value=True):
            response = client.get("/dashboard", cookies=auth_headers)
        assert response.status_code == 200
        assert "Update Available" not in response.text
```

Note: Adapt fixtures (`auth_headers`, `user`) to match the project's existing test patterns. The key logic: mock `get_update_state` and `is_update_available` at the dashboard module level, then assert banner text presence/absence in the HTML response.

**Step 2: Run integration tests**

Run: `.venv/bin/python -m pytest tests/integration/test_update_banner.py -v --no-cov`
Expected: All PASS.

**Step 3: Commit**

```bash
git add tests/integration/test_update_banner.py
git commit -m "test: add integration tests for update banner visibility"
```

---

### Task 10: Lint, Type Check & Final Verification

**Step 1: Run linting**

Run: `.venv/bin/ruff check src/splintarr/services/update_checker.py src/splintarr/api/updates.py`
Fix any issues.

**Step 2: Run type checking**

Run: `.venv/bin/mypy src/splintarr/services/update_checker.py src/splintarr/api/updates.py`
Fix any type errors. Note: `packaging` may need a type stub or `ignore_missing_imports` in `pyproject.toml` mypy config.

**Step 3: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ --no-cov`
Expected: No new failures. Pre-existing failures (~42) should not increase.

**Step 4: Check `packaging` dependency**

Verify `packaging` is in `pyproject.toml` dependencies. It's likely already present as a transitive dependency of pip/setuptools, but it should be an explicit dependency:

Run: `grep packaging pyproject.toml`

If not present, add `packaging` to `[tool.poetry.dependencies]` and run `poetry lock`.

**Step 5: Commit any fixes**

```bash
git add -u
git commit -m "chore: lint, type check, and dependency fixes for update checker"
```

---

### Summary

| Task | What | Files |
|------|------|-------|
| 1 | User model columns + migration | `models/user.py`, `alembic/versions/` |
| 2 | Service tests (red) | `tests/unit/test_update_checker.py` |
| 3 | Service implementation (green) | `services/update_checker.py` |
| 4 | API tests (red) | `tests/unit/test_updates_api.py` |
| 5 | API implementation (green) | `api/updates.py`, `main.py` |
| 6 | Scheduler integration | `main.py` |
| 7 | Dashboard banner + CSS | `dashboard/index.html`, `custom.css`, `dashboard.py` |
| 8 | Settings toggle | `settings.html`, `dashboard.py` |
| 9 | Integration tests | `tests/integration/test_update_banner.py` |
| 10 | Lint, types, final check | Various |
