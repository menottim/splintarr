# v0.3.0 Search Intelligence — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make searches smarter with adaptive scoring, tiered cooldowns, and grab detection feedback.

**Architecture:** Score items from Sonarr/Radarr API enriched with DB history, sort by priority, search top N per run. Replace in-memory 24h cooldown with persistent DB-backed tiered cooldowns. After search runs, poll command statuses to detect grabs and feed data back into scoring.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy (SQLCipher), APScheduler, Jinja2, vanilla JS

**Design doc:** `docs/plans/2026-02-28-v030-search-intelligence-design.md`

**Test commands:**
```bash
.venv/bin/python -m pytest tests/unit/ --no-cov -v -k "test_name"
.venv/bin/ruff check src/ --fix && .venv/bin/ruff format src/
```

**Pre-existing test failures:** ~123 on main. Focus on new tests only.

---

## PR 1: Data Model + Scoring Engine

**Branch:** `feat/search-scoring`

### Task 1: Add scoring/feedback columns to LibraryItem

**Files:**
- Modify: `src/splintarr/models/library.py`
- Test: `tests/unit/test_library_scoring.py` (create)

Add 4 columns to `LibraryItem` after `last_synced_at`:

```python
    # Search intelligence (v0.3.0)
    search_attempts = Column(Integer, default=0, nullable=False)
    last_searched_at = Column(DateTime, nullable=True)
    grabs_confirmed = Column(Integer, default=0, nullable=False)
    last_grab_at = Column(DateTime, nullable=True)
```

Add helper methods:

```python
    def record_search(self) -> None:
        """Record that a search was triggered for this item."""
        self.search_attempts = (self.search_attempts or 0) + 1
        self.last_searched_at = datetime.utcnow()

    def record_grab(self) -> None:
        """Record that a search resulted in a successful grab."""
        self.grabs_confirmed = (self.grabs_confirmed or 0) + 1
        self.last_grab_at = datetime.utcnow()

    @property
    def grab_rate(self) -> float:
        """Ratio of successful grabs to search attempts."""
        if not self.search_attempts:
            return 0.0
        return self.grabs_confirmed / self.search_attempts

    @property
    def consecutive_failures(self) -> int:
        """Search attempts since last grab (for cooldown backoff)."""
        return max(0, (self.search_attempts or 0) - (self.grabs_confirmed or 0))
```

**Tests:** Column defaults, record_search increments, record_grab increments, grab_rate calculation, consecutive_failures calculation.

**Commit:** `feat: add search intelligence columns to LibraryItem`

---

### Task 2: Add cooldown and batch fields to SearchQueue

**Files:**
- Modify: `src/splintarr/models/search_queue.py`
- Modify: `src/splintarr/schemas/search.py`

Add 3 columns to `SearchQueue`:

```python
    # Search intelligence (v0.3.0)
    cooldown_mode = Column(String(20), default="adaptive", nullable=False)
    cooldown_hours = Column(Integer, nullable=True)
    max_items_per_run = Column(Integer, default=50, nullable=False)
```

Update `SearchQueueCreate` schema:

```python
    cooldown_mode: Literal["adaptive", "flat"] = "adaptive"
    cooldown_hours: int | None = Field(default=None, ge=1, le=336)  # max 14 days
    max_items_per_run: int = Field(default=50, ge=1, le=500)
```

Add cross-field validator: if `cooldown_mode == "flat"`, `cooldown_hours` is required.

Update `SearchQueueUpdate` and `SearchQueueResponse` to include the new fields.

**Commit:** `feat: add cooldown mode and batch limit fields to SearchQueue`

---

### Task 3: Add feedback check delay config

**Files:**
- Modify: `src/splintarr/config.py`

```python
    # Feedback loop
    feedback_check_delay_minutes: int = Field(
        default=15,
        description="Minutes to wait before checking search command results",
        ge=5,
        le=60,
    )
```

**Commit:** `feat: add feedback check delay configuration`

---

### Task 4: Create scoring engine

**Files:**
- Create: `src/splintarr/services/scoring.py`
- Test: `tests/unit/test_scoring.py` (create)

This is the core of Feature 10. The scoring module needs:

```python
"""Search item scoring for adaptive prioritization."""

from datetime import datetime, timedelta
from typing import Any

import structlog

logger = structlog.get_logger()


def compute_score(
    record: dict[str, Any],
    library_item: Any | None,
    strategy: str,
) -> tuple[float, str]:
    """Score a search item 0-100. Returns (score, top_reason).

    Args:
        record: Item dict from Sonarr/Radarr wanted API
        library_item: LibraryItem from our DB (None if not synced yet)
        strategy: Search strategy ('missing', 'cutoff_unmet', 'recent')

    Returns:
        Tuple of (score, reason_string) where reason is the dominant factor.
    """
    recency = _recency_score(record, strategy)
    attempts = _attempts_score(library_item)
    staleness = _staleness_score(library_item)

    # Strategy weights
    if strategy == "missing":
        weighted = recency * 1.5 + attempts * 0.8 + staleness * 0.7
        max_possible = 40 * 1.5 + 30 * 0.8 + 30 * 0.7
    elif strategy == "cutoff_unmet":
        weighted = recency * 0.7 + attempts * 0.8 + staleness * 1.5
        max_possible = 40 * 0.7 + 30 * 0.8 + 30 * 1.5
    elif strategy == "recent":
        weighted = recency * 2.0 + attempts * 0.5 + staleness * 0.5
        max_possible = 40 * 2.0 + 30 * 0.5 + 30 * 0.5
    else:
        weighted = recency + attempts + staleness
        max_possible = 100.0

    # Normalize to 0-100
    score = round(min(100.0, (weighted / max_possible) * 100), 1)

    # Determine top reason
    factors = {
        "recently aired": recency,
        "never searched": attempts if attempts >= 28 else 0,
        f"searched {_get_attempts(library_item)}x, low results": attempts if 0 < attempts < 10 else 0,
        "not searched recently": staleness if staleness >= 20 else 0,
        "new to library": staleness if staleness >= 28 and _get_attempts(library_item) == 0 else 0,
    }
    top_reason = max(factors, key=factors.get) if any(factors.values()) else "default priority"

    return score, top_reason


def _recency_score(record: dict[str, Any], strategy: str) -> float:
    """Score 0-40 based on how recently content aired/was added."""
    # Get date from record — Sonarr uses airDateUtc, Radarr uses added
    date_str = record.get("airDateUtc") or record.get("added")
    if not date_str:
        return 15.0  # Unknown date gets middle score

    try:
        if isinstance(date_str, str):
            # Handle ISO format from API
            air_date = datetime.fromisoformat(date_str.replace("Z", "+00:00")).replace(tzinfo=None)
        else:
            air_date = date_str
    except (ValueError, TypeError):
        return 15.0

    age = datetime.utcnow() - air_date
    if age < timedelta(hours=24):
        return 40.0
    elif age < timedelta(days=7):
        return 30.0
    elif age < timedelta(days=30):
        return 20.0
    elif age < timedelta(days=365):
        return 10.0
    else:
        return 5.0


def _attempts_score(library_item: Any | None) -> float:
    """Score 0-30 based on search attempts. Fewer = higher."""
    attempts = _get_attempts(library_item)
    if attempts == 0:
        return 30.0
    elif attempts <= 5:
        return 25.0
    elif attempts <= 10:
        return 15.0
    elif attempts <= 20:
        return 8.0
    else:
        return 2.0


def _staleness_score(library_item: Any | None) -> float:
    """Score 0-30 based on time since last search. Longer = higher."""
    if library_item is None or library_item.last_searched_at is None:
        return 30.0  # Never searched = maximum staleness

    age = datetime.utcnow() - library_item.last_searched_at
    if age > timedelta(days=7):
        return 25.0
    elif age > timedelta(days=3):
        return 20.0
    elif age > timedelta(days=1):
        return 15.0
    else:
        return 5.0


def _get_attempts(library_item: Any | None) -> int:
    """Get search_attempts from library item, defaulting to 0."""
    if library_item is None:
        return 0
    return library_item.search_attempts or 0
```

**Tests to write (in `tests/unit/test_scoring.py`):**

1. `test_recency_score_within_24h` — air date < 24h ago → 40
2. `test_recency_score_within_7d` — 3 days ago → 30
3. `test_recency_score_within_30d` — 15 days ago → 20
4. `test_recency_score_within_1y` — 6 months ago → 10
5. `test_recency_score_over_1y` — 2 years ago → 5
6. `test_recency_score_unknown_date` — no date → 15
7. `test_attempts_score_zero` — never searched → 30
8. `test_attempts_score_few` — 3 attempts → 25
9. `test_attempts_score_moderate` — 8 attempts → 15
10. `test_attempts_score_many` — 25 attempts → 2
11. `test_staleness_score_never_searched` — None → 30
12. `test_staleness_score_old` — 10 days ago → 25
13. `test_staleness_score_recent` — 12 hours ago → 5
14. `test_compute_score_missing_strategy_favors_recency` — fresh item scores higher than old
15. `test_compute_score_cutoff_strategy_favors_staleness` — stale item scores higher
16. `test_compute_score_returns_reason` — check reason string
17. `test_compute_score_no_library_item` — None library_item → sensible defaults
18. `test_score_range_always_0_to_100` — fuzz with various inputs

**Mock pattern for library_item in tests:**
```python
from unittest.mock import MagicMock
item = MagicMock()
item.search_attempts = 5
item.last_searched_at = datetime.utcnow() - timedelta(days=3)
item.grabs_confirmed = 1
```

**Commit:** `feat: add scoring engine for adaptive search prioritization`

---

### Task 5: PR 1 finalize — lint, test, push, create PR

Run all new tests, lint, push `feat/search-scoring`, create PR.

---

## PR 2: Search Loop Integration

**Branch:** `feat/search-loop-intelligence`

### Task 6: Refactor search loop — fetch all, score, sort, search top N

**Files:**
- Modify: `src/splintarr/services/search_queue.py`
- Test: `tests/unit/test_search_scoring_integration.py` (create)

This is the biggest change. The current `_search_paginated_records` does fetch→filter→search in a single pass. We need to split it into phases:

**Phase 1: Fetch all records**
```python
async def _fetch_all_records(self, client, fetch_method, sort_key, sort_dir) -> list[dict]:
    """Fetch all wanted records from all pages."""
    all_records = []
    page = 1
    while True:
        result = await getattr(client, fetch_method)(
            page=page, page_size=50, sort_key=sort_key, sort_dir=sort_dir
        )
        records = result.get("records", [])
        if not records:
            break
        all_records.extend(records)
        if len(all_records) >= result.get("totalRecords", 0):
            break
        page += 1
    return all_records
```

**Phase 2: Enrich with scoring data**
```python
def _enrich_with_library_data(self, records, instance, db) -> dict[int, Any]:
    """Batch-load LibraryItem data for scoring. Returns {external_id: LibraryItem}."""
    # Determine content_type and external_ids from records
    external_ids = [r["id"] for r in records]  # for Radarr
    # For Sonarr, external_ids are seriesId (for exclusions) and episode id (for searching)
    # We need to look up by (instance_id, external_id, content_type)
    items = db.query(LibraryItem).filter(
        LibraryItem.instance_id == instance.id,
    ).all()
    return {item.external_id: item for item in items}
```

**Phase 3: Score, sort, filter, search**

Replace the inner loop of `_search_paginated_records` with:
1. Score all records using `compute_score()`
2. Sort by score descending
3. Filter exclusions and cooldowns
4. Truncate to `queue.max_items_per_run`
5. Search each item, calling `library_item.record_search()` after each

**Key changes to search_log entries:**
```python
# Add score and score_reason to each log entry:
log_entry = {
    "item": label,
    "action": action_name,
    "score": score,
    "score_reason": reason,
    "command_id": cmd_id,
    "result": "sent",
}
```

**Commit:** `feat: integrate scoring into search loop with fetch-all approach`

---

### Task 7: Replace in-memory cooldown with DB-backed tiered cooldown

**Files:**
- Modify: `src/splintarr/services/search_queue.py`
- Create: `src/splintarr/services/cooldown.py`
- Test: `tests/unit/test_cooldown.py` (create)

Create a cooldown service:

```python
"""Tiered cooldown logic for search items."""

from datetime import datetime, timedelta
from typing import Any

import structlog

logger = structlog.get_logger()

# Adaptive cooldown tiers (item_age -> base_cooldown_hours)
ADAPTIVE_TIERS = [
    (timedelta(hours=24), 6),
    (timedelta(days=7), 12),
    (timedelta(days=30), 24),
    (timedelta(days=365), 72),
    (None, 168),  # 7 days for >1 year old
]

MAX_COOLDOWN_HOURS = 336  # 14 days cap


def is_in_cooldown(
    library_item: Any | None,
    record: dict[str, Any],
    cooldown_mode: str,
    cooldown_hours: int | None,
) -> bool:
    """Check if an item is in cooldown.

    Args:
        library_item: LibraryItem from DB (None if not synced)
        record: Item dict from *arr API (has airDateUtc/added)
        cooldown_mode: 'adaptive' or 'flat'
        cooldown_hours: Fixed cooldown hours (when mode='flat')

    Returns:
        True if item should be skipped due to cooldown.
    """
    if library_item is None or library_item.last_searched_at is None:
        return False  # Never searched → not in cooldown

    if cooldown_mode == "flat":
        hours = cooldown_hours or 24
        return _check_cooldown(library_item.last_searched_at, hours)

    # Adaptive mode
    base_hours = _get_base_cooldown(record)
    # Apply exponential backoff for consecutive failures
    failures = library_item.consecutive_failures
    if failures > 0:
        backoff_hours = base_hours * (2 ** min(failures, 8))  # cap exponent
        effective_hours = min(backoff_hours, MAX_COOLDOWN_HOURS)
    else:
        effective_hours = base_hours

    return _check_cooldown(library_item.last_searched_at, effective_hours)


def _check_cooldown(last_searched: datetime, hours: int) -> bool:
    """Check if last_searched + hours > now."""
    cooldown_until = last_searched + timedelta(hours=hours)
    return datetime.utcnow() < cooldown_until


def _get_base_cooldown(record: dict[str, Any]) -> int:
    """Determine base cooldown hours from item age."""
    date_str = record.get("airDateUtc") or record.get("added")
    if not date_str:
        return 24  # Default to 24h for unknown dates

    try:
        if isinstance(date_str, str):
            item_date = datetime.fromisoformat(date_str.replace("Z", "+00:00")).replace(tzinfo=None)
        else:
            item_date = date_str
    except (ValueError, TypeError):
        return 24

    age = datetime.utcnow() - item_date
    for max_age, hours in ADAPTIVE_TIERS:
        if max_age is None or age < max_age:
            return hours
    return 168  # fallback
```

**Remove** the `_search_cooldowns` dict, `_is_in_cooldown`, and `_set_cooldown` methods from `SearchQueueManager`.

**Tests:**
1. Never searched → not in cooldown
2. Flat mode respects cooldown_hours
3. Adaptive tiers: item < 24h old → 6h cooldown
4. Adaptive tiers: item < 7d old → 12h cooldown
5. Adaptive tiers: item > 1y old → 7d cooldown
6. Exponential backoff: 3 consecutive failures → base × 8
7. Backoff capped at 14 days
8. Unknown date defaults to 24h

**Commit:** `feat: replace in-memory cooldown with DB-backed tiered cooldowns`

---

### Task 8: PR 2 finalize — lint, test, push, create PR

---

## PR 3: Feedback Loop Service

**Branch:** `feat/search-feedback-loop`

### Task 9: Create FeedbackCheckService

**Files:**
- Create: `src/splintarr/services/feedback.py`
- Test: `tests/unit/test_feedback.py` (create)

```python
"""Search result feedback loop — detect grabs after searches."""

import json
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy.orm import Session

from splintarr.config import settings
from splintarr.core.security import decrypt_api_key
from splintarr.models.instance import Instance
from splintarr.models.library import LibraryItem
from splintarr.models.search_history import SearchHistory
from splintarr.services.radarr import RadarrClient
from splintarr.services.sonarr import SonarrClient

logger = structlog.get_logger()


class FeedbackCheckService:
    """Polls command statuses after searches to detect grabs."""

    def __init__(self, db: Session) -> None:
        self.db = db

    async def check_search_results(self, history_id: int, instance_id: int) -> dict:
        """Check results of a completed search run.

        Polls get_command_status for each triggered search command,
        checks if items now have files, updates LibraryItem grab stats.
        """
        history = self.db.query(SearchHistory).filter(SearchHistory.id == history_id).first()
        if not history or not history.search_metadata:
            logger.warning("feedback_check_no_history", history_id=history_id)
            return {"checked": 0, "grabs": 0}

        instance = self.db.query(Instance).filter(Instance.id == instance_id).first()
        if not instance:
            logger.warning("feedback_check_no_instance", instance_id=instance_id)
            return {"checked": 0, "grabs": 0}

        try:
            metadata = json.loads(history.search_metadata)
        except (json.JSONDecodeError, TypeError):
            logger.warning("feedback_check_invalid_metadata", history_id=history_id)
            return {"checked": 0, "grabs": 0}

        # Extract entries with command_ids
        searchable = [
            entry for entry in metadata
            if entry.get("command_id") and entry.get("action") in ("EpisodeSearch", "MoviesSearch")
        ]

        if not searchable:
            return {"checked": 0, "grabs": 0}

        logger.info(
            "feedback_check_started",
            history_id=history_id,
            instance_id=instance_id,
            commands_to_check=len(searchable),
        )

        api_key = decrypt_api_key(instance.api_key)
        is_sonarr = instance.instance_type == "sonarr"
        client_cls = SonarrClient if is_sonarr else RadarrClient

        grabs = 0
        checked = 0

        try:
            async with client_cls(
                url=instance.url,
                api_key=api_key,
                verify_ssl=instance.verify_ssl,
                rate_limit_per_second=instance.rate_limit_per_second or 5,
            ) as client:
                for entry in searchable:
                    try:
                        cmd_status = await client.get_command_status(entry["command_id"])
                        checked += 1

                        if cmd_status.get("status") == "completed":
                            # Check if item now has a file
                            grabbed = await self._check_has_file(
                                client, entry, is_sonarr
                            )
                            entry["grab_confirmed"] = grabbed
                            if grabbed:
                                grabs += 1
                                self._update_library_item_grab(instance, entry, is_sonarr)
                        else:
                            entry["grab_confirmed"] = False
                            entry["command_status"] = cmd_status.get("status", "unknown")

                    except Exception as e:
                        logger.warning(
                            "feedback_check_command_failed",
                            command_id=entry.get("command_id"),
                            error=str(e),
                        )
                        entry["grab_confirmed"] = None  # unknown

        except Exception as e:
            logger.error(
                "feedback_check_client_failed",
                instance_id=instance_id,
                error=str(e),
            )

        # Update search_metadata with grab results
        history.search_metadata = json.dumps(metadata)
        self.db.commit()

        logger.info(
            "feedback_check_completed",
            history_id=history_id,
            checked=checked,
            grabs=grabs,
        )

        return {"checked": checked, "grabs": grabs}

    async def _check_has_file(self, client, entry: dict, is_sonarr: bool) -> bool:
        """Check if the searched item now has a file."""
        try:
            item_id = entry.get("item_id")
            if not item_id:
                return False

            if is_sonarr:
                # For episodes, check via series episodes endpoint
                series_id = entry.get("series_id")
                if series_id:
                    episodes = await client.get_episodes(series_id)
                    for ep in episodes:
                        if ep.get("id") == item_id and ep.get("hasFile"):
                            return True
                return False
            else:
                # For movies, check directly
                movies = await client.get_movies(item_id)
                if isinstance(movies, dict):
                    return movies.get("hasFile", False)
                return False
        except Exception:
            return False

    def _update_library_item_grab(self, instance: Instance, entry: dict, is_sonarr: bool) -> None:
        """Update LibraryItem with grab confirmation."""
        external_id = entry.get("series_id") if is_sonarr else entry.get("item_id")
        content_type = "series" if is_sonarr else "movie"

        if external_id:
            library_item = self.db.query(LibraryItem).filter(
                LibraryItem.instance_id == instance.id,
                LibraryItem.external_id == external_id,
                LibraryItem.content_type == content_type,
            ).first()

            if library_item:
                library_item.record_grab()
                logger.info(
                    "feedback_grab_confirmed",
                    instance_id=instance.id,
                    external_id=external_id,
                    content_type=content_type,
                    title=entry.get("item", "unknown"),
                )
```

**Important:** The search_log entries need to include `item_id` and `series_id` (for Sonarr) so the feedback service can look up the item. This must be added in Task 6 when we modify the search loop.

**Tests:**
1. No history record → returns {checked: 0, grabs: 0}
2. No searchable commands → returns {checked: 0, grabs: 0}
3. Command completed + hasFile → grab confirmed, LibraryItem updated
4. Command completed + no file → grab_confirmed = False
5. Command failed/queued → grab_confirmed = False
6. Client exception caught gracefully

**Commit:** `feat: add FeedbackCheckService for grab detection`

---

### Task 10: Schedule feedback check after search runs

**Files:**
- Modify: `src/splintarr/services/scheduler.py`
- Modify: `src/splintarr/services/search_queue.py` (at end of execute_queue)

In `execute_queue()`, after successful completion with `searches_triggered > 0`:

```python
# Schedule feedback check
try:
    from splintarr.services.scheduler import get_scheduler
    scheduler = get_scheduler(self.db_session_factory)
    scheduler.scheduler.add_job(
        scheduler._execute_feedback_check,
        trigger="date",
        run_date=datetime.utcnow() + timedelta(minutes=settings.feedback_check_delay_minutes),
        id=f"feedback_check_{history.id}",
        args=[history.id, instance.id],
        replace_existing=True,
    )
    logger.info(
        "feedback_check_scheduled",
        history_id=history.id,
        delay_minutes=settings.feedback_check_delay_minutes,
    )
except Exception as e:
    logger.warning("feedback_check_schedule_failed", error=str(e))
```

In `scheduler.py`, add `_execute_feedback_check`:

```python
async def _execute_feedback_check(self, history_id: int, instance_id: int) -> None:
    """Execute feedback check for a completed search run."""
    db = self.db_session_factory()
    try:
        service = FeedbackCheckService(db)
        result = await service.check_search_results(history_id, instance_id)
        logger.info(
            "feedback_check_execution_completed",
            history_id=history_id,
            **result,
        )
    except Exception as e:
        logger.error("feedback_check_execution_failed", history_id=history_id, error=str(e))
    finally:
        db.close()
```

**Commit:** `feat: schedule feedback check after search completion`

---

### Task 11: PR 3 finalize — lint, test, push, create PR

---

## PR 4: UI Updates

**Branch:** `feat/search-intelligence-ui`

### Task 12: Show score in search log on queue detail page

**Files:**
- Modify: `src/splintarr/api/dashboard.py` (update `parse_search_log` filter)
- Modify: `src/splintarr/templates/dashboard/search_queue_detail.html`

Update the `_parse_search_log` Jinja2 filter to render score and reason:

```python
# In the parse_search_log filter, for each entry:
if "score" in entry:
    parts.append(f"Score: {entry['score']}")
if "score_reason" in entry:
    parts.append(f"({entry['score_reason']})")
if "grab_confirmed" in entry:
    if entry["grab_confirmed"]:
        parts.append("✓ Grabbed")
    elif entry["grab_confirmed"] is False:
        parts.append("○ No grab")
```

**Commit:** `feat: show score and grab status in search log`

---

### Task 13: Show search stats on library detail page

**Files:**
- Modify: `src/splintarr/templates/dashboard/library_detail.html`
- Modify: `src/splintarr/api/library.py` (pass scoring data to template if needed)

Add a "Search Intelligence" section to the library detail page:

```html
{% if item.search_attempts is not none and item.search_attempts > 0 %}
<article>
    <header><h4>Search Stats</h4></header>
    <dl>
        <dt>Search Attempts</dt>
        <dd>{{ item.search_attempts }}</dd>
        <dt>Grabs Confirmed</dt>
        <dd>{{ item.grabs_confirmed or 0 }}</dd>
        {% if item.last_searched_at %}
        <dt>Last Searched</dt>
        <dd>{{ item.last_searched_at|timeago }}</dd>
        {% endif %}
        {% if item.last_grab_at %}
        <dt>Last Grab</dt>
        <dd>{{ item.last_grab_at|timeago }}</dd>
        {% endif %}
    </dl>
</article>
{% endif %}
```

**Commit:** `feat: show search stats on library detail page`

---

### Task 14: Add cooldown and batch config to queue modal

**Files:**
- Modify: `src/splintarr/templates/dashboard/search_queues.html`

Add to the Create Queue modal form:

```html
<label>
    Cooldown Mode
    <select id="cooldown_mode" name="cooldown_mode">
        <option value="adaptive">Adaptive (recommended)</option>
        <option value="flat">Fixed interval</option>
    </select>
</label>
<div id="flatCooldownRow" style="display: none;">
    <label>
        Cooldown Hours
        <input type="number" id="cooldown_hours" name="cooldown_hours" min="1" max="336" value="24">
    </label>
</div>
<label>
    Max Items Per Run
    <input type="number" id="max_items_per_run" name="max_items_per_run" min="1" max="500" value="50">
</label>
```

Add JS to toggle flat cooldown row:

```javascript
document.getElementById('cooldown_mode').addEventListener('change', function() {
    document.getElementById('flatCooldownRow').style.display =
        this.value === 'flat' ? '' : 'none';
});
```

Update `getFormData()` and `createQueue()` to include the new fields.

Update `cloneQueue()` to pre-fill the new fields from source queue.

Update preset definitions to include `cooldown_mode: 'adaptive'` and `max_items_per_run`.

**Commit:** `feat: add cooldown and batch config to queue UI`

---

### Task 15: Add grab rate to dashboard

**Files:**
- Modify: `src/splintarr/api/dashboard.py` (stats endpoint)
- Modify: `src/splintarr/templates/dashboard/index.html`

In the `/api/dashboard/stats` endpoint, add grab rate calculation:

```python
# Query total searches_triggered and grabs from search_metadata
# Or simpler: sum LibraryItem.search_attempts and grabs_confirmed
total_searches = db.query(func.sum(LibraryItem.search_attempts)).scalar() or 0
total_grabs = db.query(func.sum(LibraryItem.grabs_confirmed)).scalar() or 0
grab_rate = round((total_grabs / total_searches * 100), 1) if total_searches > 0 else 0.0
```

Add to the dashboard stats card area or as a detail under "Searches Today":

```javascript
// In the stats refresh JS, show grab rate
if (stats.grab_rate !== undefined) {
    var grEl = document.getElementById('stat-grab-rate');
    if (grEl) grEl.textContent = stats.grab_rate + '% grab rate';
}
```

**Commit:** `feat: add grab rate metric to dashboard`

---

### Task 16: PR 4 finalize — lint, test, push, create PR

---

## Post-Implementation

After all 4 PRs merged:
1. Update `docs/PRD.md` — mark Features 10, 11, 12 as Done
2. Bump version to `0.3.0` in `pyproject.toml`
3. Update README version + release link
4. Create GitHub release
5. Run code simplifier

## Dependency Graph

```
PR 1 (Data Model + Scoring)  ─→  PR 2 (Search Loop Integration)
                                         │
                               PR 3 (Feedback Loop)  ─→  PR 4 (UI Updates)
```

PR 1 must merge before PR 2. PR 3 depends on PR 2 (needs the enriched search_log entries with item_id/series_id). PR 4 depends on all 3.
