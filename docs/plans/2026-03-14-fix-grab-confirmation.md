# Fix Grab Confirmation (#130) — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix false grab detection by using Sonarr's history API instead of `hasFile` checks, and fix the dashboard grab count to use 7-day SearchHistory data.

**Architecture:** Add `get_history()` to SonarrClient, rewrite feedback.py's `_check_sonarr_episode` to query grabbed events from Sonarr history with temporal correlation, switch dashboard grab stats to SearchHistory-based 7-day count, and reset stale LibraryItem.grabs_confirmed data.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy, httpx, structlog, pytest-asyncio

---

### Task 1: Add `get_history` method to SonarrClient

**Files:**
- Modify: `src/splintarr/services/sonarr.py` (append after `get_poster_bytes`)
- Test: `tests/unit/test_sonarr_history.py` (create)

**Step 1: Write the failing test**

Create `tests/unit/test_sonarr_history.py`:

```python
"""Tests for Sonarr history API method."""
import pytest
from unittest.mock import AsyncMock, patch

from splintarr.services.sonarr import SonarrClient


class TestGetHistory:
    """Test get_history method."""

    @pytest.mark.asyncio
    async def test_returns_grabbed_records(self):
        mock_response = {
            "records": [
                {
                    "id": 1,
                    "episodeId": 42,
                    "eventType": "grabbed",
                    "date": "2026-03-14T10:30:00Z",
                    "sourceTitle": "Show.S01E01.1080p.WEB-DL",
                    "downloadId": "abc123",
                },
            ]
        }
        async with SonarrClient(
            url="http://localhost:8989",
            api_key="test-key",
        ) as client:
            with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_response):
                result = await client.get_history(episode_id=42, event_type="grabbed")
                assert len(result) == 1
                assert result[0]["episodeId"] == 42
                assert result[0]["eventType"] == "grabbed"

    @pytest.mark.asyncio
    async def test_passes_correct_params(self):
        mock_response = {"records": []}
        async with SonarrClient(
            url="http://localhost:8989",
            api_key="test-key",
        ) as client:
            with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_response) as mock_req:
                await client.get_history(episode_id=42, event_type="grabbed")
                mock_req.assert_called_once_with(
                    "GET",
                    "/api/v3/history",
                    params={"episodeId": 42, "eventType": "grabbed", "pageSize": 10},
                )

    @pytest.mark.asyncio
    async def test_returns_empty_on_no_records(self):
        mock_response = {"records": []}
        async with SonarrClient(
            url="http://localhost:8989",
            api_key="test-key",
        ) as client:
            with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_response):
                result = await client.get_history(episode_id=99)
                assert result == []
```

**Step 2: Run tests to verify they fail**

Run: `cd /tmp/splintarr && poetry run pytest tests/unit/test_sonarr_history.py -v --no-cov`
Expected: FAIL — `AttributeError: 'SonarrClient' object has no attribute 'get_history'`

**Step 3: Write implementation**

Add to `src/splintarr/services/sonarr.py`, after `get_poster_bytes`:

```python
    async def get_history(
        self,
        episode_id: int,
        event_type: str | None = None,
        page_size: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Get history records for an episode from Sonarr.

        Args:
            episode_id: Episode ID to get history for
            event_type: Optional event type filter (e.g. 'grabbed')
            page_size: Max records to return (default 10)

        Returns:
            list[dict]: History records matching the filters
        """
        params: dict[str, Any] = {
            "episodeId": episode_id,
            "pageSize": page_size,
        }
        if event_type:
            params["eventType"] = event_type

        result = await self._request("GET", "/api/v3/history", params=params)

        records = result.get("records", []) if isinstance(result, dict) else []
        logger.debug(
            "sonarr_history_retrieved",
            episode_id=episode_id,
            event_type=event_type,
            count=len(records),
        )
        return records
```

**Step 4: Run tests to verify they pass**

Run: `cd /tmp/splintarr && poetry run pytest tests/unit/test_sonarr_history.py -v --no-cov`
Expected: 3 passed

**Step 5: Commit**

```bash
cd /tmp/splintarr
git add src/splintarr/services/sonarr.py tests/unit/test_sonarr_history.py
git -c user.name="menottim" -c user.email="menottim@users.noreply.github.com" commit -m "feat: add get_history method to SonarrClient"
```

---

### Task 2: Record command issued timestamp in search metadata

**Files:**
- Modify: `src/splintarr/services/search_queue.py:862-873` (add `command_issued_at` field to search_log entries)

**Step 1: Add `command_issued_at` to search log entries**

In `src/splintarr/services/search_queue.py`, every place that appends to `search_log` with a `command_id` needs a timestamp. There are three locations:

**Location A — individual episode search (around line 862):**

Find the dict that starts with `"item": label, "action": action_name,` and add after `"result": "sent",`:

```python
                                "command_issued_at": datetime.utcnow().isoformat() + "Z",
```

**Location B — season pack search (around line 780):**

Find the dict that starts with `"item": label, "action": "SeasonSearch",` and add after `"result": "sent",`:

```python
                                            "command_issued_at": datetime.utcnow().isoformat() + "Z",
```

**Location C — any other search log append with a command_id.** Search the file for all `"command_id":` entries in search_log dicts and ensure each one also has `command_issued_at`.

Note: `datetime` is already imported at the top of search_queue.py (`from datetime import UTC, datetime, timedelta`).

**Step 2: Run existing tests to confirm no regressions**

Run: `cd /tmp/splintarr && poetry run pytest tests/ -v --no-cov -x`
Expected: All existing tests pass

**Step 3: Commit**

```bash
cd /tmp/splintarr
git add src/splintarr/services/search_queue.py
git -c user.name="menottim" -c user.email="menottim@users.noreply.github.com" commit -m "feat: record command_issued_at timestamp in search metadata"
```

---

### Task 3: Rewrite feedback check to use Sonarr history API

**Files:**
- Modify: `src/splintarr/services/feedback.py:203-238` (replace `_check_single_command` and `_check_sonarr_episode`)
- Test: `tests/unit/test_feedback_history.py` (create)

**Step 1: Write the failing tests**

Create `tests/unit/test_feedback_history.py`:

```python
"""Tests for feedback check using Sonarr history API."""
import pytest
from unittest.mock import AsyncMock, patch

from splintarr.services.feedback import FeedbackCheckService


class TestCheckSonarrEpisodeViaHistory:
    """Test _check_sonarr_episode uses history API instead of hasFile."""

    @pytest.mark.asyncio
    async def test_confirms_grab_when_history_has_grabbed_event_after_command(self):
        """A grabbed event AFTER command_issued_at = confirmed grab."""
        service = FeedbackCheckService(db=None)
        mock_client = AsyncMock()
        mock_client.get_history = AsyncMock(return_value=[
            {
                "episodeId": 42,
                "eventType": "grabbed",
                "date": "2026-03-14T10:35:00Z",
                "sourceTitle": "Show.S01E01.1080p",
            },
        ])

        entry = {
            "item_id": 42,
            "series_id": 100,
            "command_issued_at": "2026-03-14T10:30:00Z",
        }

        result = await service._check_sonarr_episode(mock_client, entry)
        assert result is True
        # Verify sourceTitle was recorded on entry
        assert entry.get("source_title") == "Show.S01E01.1080p"

    @pytest.mark.asyncio
    async def test_rejects_grab_when_history_event_before_command(self):
        """A grabbed event BEFORE command_issued_at = not our grab."""
        service = FeedbackCheckService(db=None)
        mock_client = AsyncMock()
        mock_client.get_history = AsyncMock(return_value=[
            {
                "episodeId": 42,
                "eventType": "grabbed",
                "date": "2026-03-14T10:25:00Z",  # Before command
                "sourceTitle": "Show.S01E01.720p",
            },
        ])

        entry = {
            "item_id": 42,
            "series_id": 100,
            "command_issued_at": "2026-03-14T10:30:00Z",
        }

        result = await service._check_sonarr_episode(mock_client, entry)
        assert result is False
        assert "source_title" not in entry

    @pytest.mark.asyncio
    async def test_rejects_grab_when_no_history(self):
        """No grabbed events = no grab."""
        service = FeedbackCheckService(db=None)
        mock_client = AsyncMock()
        mock_client.get_history = AsyncMock(return_value=[])

        entry = {
            "item_id": 42,
            "series_id": 100,
            "command_issued_at": "2026-03-14T10:30:00Z",
        }

        result = await service._check_sonarr_episode(mock_client, entry)
        assert result is False

    @pytest.mark.asyncio
    async def test_fallback_to_hasfile_when_no_timestamp(self):
        """If command_issued_at is missing (old data), fall back to hasFile check."""
        service = FeedbackCheckService(db=None)
        mock_client = AsyncMock()
        mock_client.get_episodes = AsyncMock(return_value=[
            {"id": 42, "hasFile": True},
        ])

        entry = {
            "item_id": 42,
            "series_id": 100,
            # No command_issued_at — old metadata format
        }

        result = await service._check_sonarr_episode(mock_client, entry)
        assert result is True
```

**Step 2: Run tests to verify they fail**

Run: `cd /tmp/splintarr && poetry run pytest tests/unit/test_feedback_history.py -v --no-cov`
Expected: FAIL (current `_check_sonarr_episode` doesn't use history API)

**Step 3: Rewrite `_check_sonarr_episode` in `src/splintarr/services/feedback.py`**

Add `from datetime import datetime` at the top of feedback.py (after the existing imports).

Replace the `_check_sonarr_episode` method (lines 223-238) with:

```python
    async def _check_sonarr_episode(
        self,
        client: SonarrClient,
        entry: dict[str, Any],
    ) -> bool:
        """Check if a Sonarr episode was grabbed after our search command.

        Uses Sonarr's history API to find 'grabbed' events for this episode
        that occurred after the search command was issued. Falls back to
        hasFile check for old metadata without command_issued_at.
        """
        item_id = entry.get("item_id")
        series_id = entry.get("series_id")
        if not item_id:
            return False

        command_issued_at = entry.get("command_issued_at")

        # Fallback for old metadata without timestamp: use legacy hasFile check
        if not command_issued_at:
            if not series_id:
                return False
            episodes = await client.get_episodes(series_id)
            for ep in episodes:
                if ep.get("id") == item_id and ep.get("hasFile") is True:
                    return True
            return False

        # Use history API: find grabbed events after our command
        try:
            history_records = await client.get_history(
                episode_id=item_id,
                event_type="grabbed",
            )
        except Exception as e:
            logger.warning(
                "feedback_check_history_failed",
                episode_id=item_id,
                error=str(e),
            )
            return False

        # Parse command timestamp for comparison
        try:
            command_time = datetime.fromisoformat(command_issued_at.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return False

        for record in history_records:
            record_date = record.get("date", "")
            try:
                grab_time = datetime.fromisoformat(record_date.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue

            if grab_time > command_time:
                # This grab happened after our search — attribute it to us
                entry["source_title"] = record.get("sourceTitle")
                return True

        return False
```

**Step 4: Run tests to verify they pass**

Run: `cd /tmp/splintarr && poetry run pytest tests/unit/test_feedback_history.py -v --no-cov`
Expected: 4 passed

**Step 5: Commit**

```bash
cd /tmp/splintarr
git add src/splintarr/services/feedback.py tests/unit/test_feedback_history.py
git -c user.name="menottim" -c user.email="menottim@users.noreply.github.com" commit -m "fix: use Sonarr history API for grab detection instead of hasFile"
```

---

### Task 4: Switch dashboard grab stats to 7-day SearchHistory

**Files:**
- Modify: `src/splintarr/api/dashboard.py:1266-1280` (replace grab stats query)

**Step 1: Rewrite the grab stats block**

In `src/splintarr/api/dashboard.py`, replace the block at lines 1266-1280 (from `# Grab rate from library search intelligence` through `grab_rate = ...`) with:

```python
    # Grab rate from search history (last 7 days, matching analytics scope)
    user_instance_ids = db.query(Instance.id).filter(Instance.user_id == user.id)
    recent_histories = (
        db.query(SearchHistory.search_metadata)
        .join(Instance, SearchHistory.instance_id == Instance.id)
        .filter(
            Instance.user_id == user.id,
            SearchHistory.started_at >= week_ago,
            SearchHistory.search_metadata.isnot(None),
        )
        .all()
    )

    total_grabs = 0
    total_checked = 0
    for (metadata_json,) in recent_histories:
        try:
            entries = json.loads(metadata_json)
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict) and entry.get("result") in ("grabbed", "no grab"):
                        total_checked += 1
                        if entry.get("result") == "grabbed":
                            total_grabs += 1
        except (json.JSONDecodeError, TypeError):
            continue

    grab_rate = round(total_grabs / total_checked * 100, 1) if total_checked > 0 else 0.0
```

Note: `json` is already imported at the top of dashboard.py. `week_ago` is already computed earlier in this function. The variable `total_search_attempts` is no longer needed — replace it in the return dict (check if it's used elsewhere in the return value at line 1282+).

Also update the return dict — change:
```python
        "grab_rate": grab_rate,
```
to also include `total_grabs` for the dashboard card:
```python
        "grab_rate": grab_rate,
        "grabs_confirmed": total_grabs,
```

**Step 2: Check the dashboard template for how grab_rate/grabs are displayed**

Search for `grab_rate` or `grabs_confirmed` in the dashboard template and update any references if needed.

**Step 3: Run existing tests to confirm no regressions**

Run: `cd /tmp/splintarr && poetry run pytest tests/ -v --no-cov -x`
Expected: All existing tests pass

**Step 4: Commit**

```bash
cd /tmp/splintarr
git add src/splintarr/api/dashboard.py
git -c user.name="menottim" -c user.email="menottim@users.noreply.github.com" commit -m "fix: dashboard grab count uses 7-day SearchHistory instead of lifetime LibraryItem sum"
```

---

### Task 5: Reset stale grabs_confirmed data

**Files:**
- Modify: `src/splintarr/database.py` (add one-time reset after `create_all`)

**Step 1: Add reset logic**

In `src/splintarr/database.py`, after the `Base.metadata.create_all(bind=engine)` call (line 330), add:

```python
    # One-time reset: zero out grabs_confirmed data that was
    # inflated by the pre-v1.4.0 hasFile-based grab detection.
    # See: https://github.com/menottim/splintarr/issues/130
    try:
        with Session(engine) as session:
            from splintarr.models.library import LibraryItem

            reset_count = (
                session.query(LibraryItem)
                .filter(LibraryItem.grabs_confirmed > 0)
                .update({"grabs_confirmed": 0, "last_grab_at": None})
            )
            if reset_count > 0:
                session.commit()
                logger.info("grabs_confirmed_reset", items_reset=reset_count)
    except Exception as e:
        logger.warning("grabs_confirmed_reset_failed", error=str(e))
```

Note: This runs on every startup but is harmless after the first run (0 rows match the filter once data is clean). The `Session` import and `logger` should already be available in this file.

**Step 2: Verify imports**

Check that `Session` from sqlalchemy.orm and `structlog` logger are available in database.py. If not, add them.

**Step 3: Run existing tests**

Run: `cd /tmp/splintarr && poetry run pytest tests/ -v --no-cov -x`
Expected: All existing tests pass

**Step 4: Commit**

```bash
cd /tmp/splintarr
git add src/splintarr/database.py
git -c user.name="menottim" -c user.email="menottim@users.noreply.github.com" commit -m "fix: reset inflated grabs_confirmed data on startup (#130)"
```

---

### Task 6: Full test suite + lint check

**Files:** None (validation only)

**Step 1: Run full test suite with coverage**

Run: `cd /tmp/splintarr && poetry run pytest tests/ -v`
Expected: All tests pass, coverage >= 80%

**Step 2: Run linter**

Run: `cd /tmp/splintarr && poetry run ruff check src/`
Expected: No errors

**Step 3: Run type checker**

Run: `cd /tmp/splintarr && poetry run mypy src/`
Expected: No new errors

**Step 4: Run security linter**

Run: `cd /tmp/splintarr && poetry run bandit -r src/ -c pyproject.toml`
Expected: No new findings
