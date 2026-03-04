# Indexer Budget Visibility Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add visual progress bars for indexer API usage, budget alert notifications, and smart batch auto-sizing to search queues.

**Architecture:** Three independent features layered on existing Prowlarr integration. (1) Progress bars replace "X of Y" text in dashboard indexer widget via JS DOM changes. (2) Budget alerts fire Discord notifications at 80%+ usage with per-period dedup. (3) `budget_aware` boolean on SearchQueue controls proportional batch reduction.

**Tech Stack:** Python/FastAPI, Jinja2 templates, Pico CSS, structlog, existing Prowlarr client + IndexerRateLimitService

---

### Task 1: Progress Bars in Dashboard Indexer Widget

**Files:**
- Modify: `src/splintarr/templates/dashboard/index.html:176-191` (table structure)
- Modify: `src/splintarr/templates/dashboard/index.html:666-711` (buildIndexerRow JS)

**Step 1: Replace the table "Queries Used" column with a progress bar**

Change the HTML table header from separate "Query Limit" and "Queries Used" columns to a single "Usage" column:

```html
<table id="indexer-health-table" role="grid">
    <thead>
        <tr>
            <th>Indexer</th>
            <th data-tooltip="API query usage relative to indexer limit">Usage</th>
            <th>Status</th>
        </tr>
    </thead>
    <tbody id="indexer-health-body">
        <tr>
            <td colspan="3" style="text-align: center; color: var(--muted-color);">Loading...</td>
        </tr>
    </tbody>
</table>
```

**Step 2: Update `buildIndexerRow` to render a progress bar**

Replace the existing Query Limit + Queries Used cells with a single Usage cell containing a progress bar:

```javascript
function buildIndexerRow(idx) {
    var row = document.createElement('tr');

    // Name
    var nameCell = document.createElement('td');
    nameCell.textContent = idx.name;
    row.appendChild(nameCell);

    // Usage (progress bar + text)
    var usageCell = document.createElement('td');
    if (idx.query_limit) {
        var pct = Math.min(100, Math.round((idx.queries_used / idx.query_limit) * 100));
        var unit = idx.limits_unit || 'day';

        // Color based on usage percentage
        var barColor;
        if (pct >= 80) barColor = 'var(--del-color)';
        else if (pct >= 60) barColor = 'var(--mark-background-color)';
        else barColor = 'var(--ins-color)';

        // Progress bar container
        var barOuter = document.createElement('div');
        barOuter.style.cssText = 'background:var(--muted-border-color);border-radius:4px;height:8px;width:100%;margin-bottom:2px;';

        var barInner = document.createElement('div');
        barInner.style.cssText = 'height:100%;border-radius:4px;transition:width 0.3s;';
        barInner.style.width = pct + '%';
        barInner.style.backgroundColor = barColor;
        barOuter.appendChild(barInner);
        usageCell.appendChild(barOuter);

        // Text label below bar
        var label = document.createElement('small');
        label.style.color = 'var(--muted-color)';
        label.textContent = idx.queries_used + ' / ' + idx.query_limit + ' per ' + unit + ' (' + pct + '%)';
        usageCell.appendChild(label);
    } else {
        usageCell.style.color = 'var(--muted-color)';
        usageCell.textContent = idx.queries_used + ' queries (no limit)';
    }
    row.appendChild(usageCell);

    // Status
    var statusCell = document.createElement('td');
    var statusSpan = document.createElement('span');
    if (idx.is_disabled) {
        statusSpan.style.color = 'var(--del-color)';
        statusSpan.textContent = 'Disabled';
    } else {
        statusSpan.style.color = 'var(--ins-color)';
        statusSpan.textContent = 'Active';
    }
    statusCell.appendChild(statusSpan);
    row.appendChild(statusCell);

    return row;
}
```

**Step 3: Update demo data to include `limits_unit`**

Check that `get_demo_indexer_health()` in `src/splintarr/services/demo.py` includes `limits_unit` on each indexer. If missing, add `"limits_unit": "day"`.

**Step 4: Verify visually**

Build and run Docker container. Confirm the indexer widget shows progress bars with correct coloring.

**Step 5: Commit**

```bash
git add src/splintarr/templates/dashboard/index.html src/splintarr/services/demo.py
git commit -m "feat: replace indexer usage text with visual progress bars

Color-coded bars: green (<60%), gold (60-80%), red (>80%).
Text label shows 'X / Y per day (Z%)' below the bar."
```

---

### Task 2: Budget Alert Notification — Discord Method

**Files:**
- Modify: `src/splintarr/services/discord.py` (add `send_budget_alert` before `send_test_message`)
- Modify: `src/splintarr/models/notification.py:19-26` (add `budget_alert` to DEFAULT_EVENTS)
- Modify: `src/splintarr/templates/dashboard/settings.html` (add checkbox)
- Modify: `src/splintarr/templates/setup/notifications.html` (add default)

**Step 1: Write the failing test**

Create `tests/unit/test_budget_alert_notification.py`:

```python
"""Tests for budget alert Discord notification."""
import pytest
from unittest.mock import AsyncMock, patch

from splintarr.services.discord import DiscordNotificationService


class TestSendBudgetAlert:
    """Test send_budget_alert Discord embed."""

    @pytest.mark.asyncio
    async def test_sends_red_embed(self):
        service = DiscordNotificationService("https://discord.com/api/webhooks/test")
        with patch.object(service, "_send_embed", new_callable=AsyncMock, return_value=True) as mock:
            result = await service.send_budget_alert(
                indexer_name="NZBgeek",
                queries_used=85,
                query_limit=100,
                percent_used=85,
            )
            assert result is True
            embed = mock.call_args[0][0]
            assert "NZBgeek" in embed["title"]
            assert embed["color"] == 0xE74C3C  # COLOR_RED
            assert "85" in embed["description"]
            assert "100" in embed["description"]

    @pytest.mark.asyncio
    async def test_embed_includes_percentage(self):
        service = DiscordNotificationService("https://discord.com/api/webhooks/test")
        with patch.object(service, "_send_embed", new_callable=AsyncMock, return_value=True) as mock:
            await service.send_budget_alert(
                indexer_name="NZBgeek",
                queries_used=90,
                query_limit=100,
                percent_used=90,
            )
            embed = mock.call_args[0][0]
            assert "90%" in embed["description"]
```

**Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest tests/unit/test_budget_alert_notification.py -v --no-cov
```

Expected: FAIL — `send_budget_alert` does not exist.

**Step 3: Implement `send_budget_alert` in discord.py**

Add before `send_test_message()`:

```python
    async def send_budget_alert(
        self,
        indexer_name: str,
        queries_used: int,
        query_limit: int,
        percent_used: int,
    ) -> bool:
        """Send a budget alert when indexer API usage is high.

        Args:
            indexer_name: Name of the indexer
            queries_used: Current query count
            query_limit: Maximum allowed queries
            percent_used: Usage percentage (0-100)

        Returns:
            bool: True if the webhook accepted the message
        """
        embed: dict = {
            "title": f"Indexer Budget Alert: {indexer_name}",
            "description": (
                f"**Usage:** {queries_used} / {query_limit} ({percent_used}%)\n"
                f"**Indexer:** {indexer_name}\n"
                f"API budget is running low. Search batch sizes may be reduced automatically."
            ),
            "color": COLOR_RED,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "footer": {"text": "Splintarr"},
        }

        logger.info(
            "discord_notification_budget_alert_sent",
            indexer_name=indexer_name,
            percent_used=percent_used,
        )

        return await self._send_embed(embed)
```

**Step 4: Run test to verify it passes**

```bash
.venv/bin/python -m pytest tests/unit/test_budget_alert_notification.py -v --no-cov
```

**Step 5: Add `budget_alert` to DEFAULT_EVENTS**

In `src/splintarr/models/notification.py`, add `"budget_alert": True` to the dict.

**Step 6: Update Settings UI and setup wizard**

In `settings.html`, add after the `grab_confirmed` checkbox:
```html
<label>
    <input type="checkbox" id="evt_budget_alert" name="budget_alert" checked>
    Indexer budget alert
</label>
```

Add to the JS load block: `document.getElementById('evt_budget_alert').checked = data.events_enabled.budget_alert !== false;`

Add to both save payload blocks: `budget_alert: document.getElementById('evt_budget_alert').checked,`

In `setup/notifications.html`, add `budget_alert: true` to the events_enabled object.

**Step 7: Commit**

```bash
git add src/splintarr/services/discord.py src/splintarr/models/notification.py \
  src/splintarr/templates/dashboard/settings.html src/splintarr/templates/setup/notifications.html \
  tests/unit/test_budget_alert_notification.py
git commit -m "feat: add budget_alert Discord notification method and toggle

Red embed fires when indexer API usage exceeds 80%. New toggle in
Settings and setup wizard defaults."
```

---

### Task 3: Budget Alert Trigger with Dedup

**Files:**
- Modify: `src/splintarr/api/dashboard.py` (indexer-health endpoint, add alert check)

**Step 1: Write the failing test**

Create `tests/unit/test_budget_alert_dedup.py`:

```python
"""Tests for budget alert dedup logic."""
import pytest

from splintarr.api.dashboard import _check_budget_alerts, _alerted_indexers


class TestBudgetAlertDedup:
    """Test that budget alerts fire once per indexer per period."""

    def setup_method(self):
        _alerted_indexers.clear()

    def test_alert_fires_on_first_high_usage(self):
        alerts = _check_budget_alerts([
            {"name": "NZBgeek", "query_limit": 100, "queries_used": 85, "limits_unit": "day"},
        ])
        assert len(alerts) == 1
        assert alerts[0]["indexer_name"] == "NZBgeek"

    def test_alert_does_not_repeat(self):
        _check_budget_alerts([
            {"name": "NZBgeek", "query_limit": 100, "queries_used": 85, "limits_unit": "day"},
        ])
        alerts = _check_budget_alerts([
            {"name": "NZBgeek", "query_limit": 100, "queries_used": 90, "limits_unit": "day"},
        ])
        assert len(alerts) == 0

    def test_no_alert_below_threshold(self):
        alerts = _check_budget_alerts([
            {"name": "NZBgeek", "query_limit": 100, "queries_used": 50, "limits_unit": "day"},
        ])
        assert len(alerts) == 0

    def test_no_alert_without_limit(self):
        alerts = _check_budget_alerts([
            {"name": "NZBgeek", "query_limit": None, "queries_used": 500, "limits_unit": "day"},
        ])
        assert len(alerts) == 0
```

**Step 2: Run test to verify it fails**

**Step 3: Implement `_check_budget_alerts` and wire into endpoint**

Add module-level state and helper in `dashboard.py`:

```python
# Budget alert dedup — tracks which indexers have been alerted this period
_alerted_indexers: set[str] = set()

BUDGET_ALERT_THRESHOLD = 80  # percent


def _check_budget_alerts(indexers: list[dict]) -> list[dict]:
    """Check indexer usage and return alerts for newly-over-threshold indexers."""
    alerts = []
    for idx in indexers:
        limit = idx.get("query_limit")
        if not limit:
            continue
        used = idx.get("queries_used", 0)
        pct = round(used / limit * 100)
        key = f"{idx['name']}:{idx.get('limits_unit', 'day')}"
        if pct >= BUDGET_ALERT_THRESHOLD and key not in _alerted_indexers:
            _alerted_indexers.add(key)
            alerts.append({
                "indexer_name": idx["name"],
                "queries_used": used,
                "query_limit": limit,
                "percent_used": pct,
            })
    return alerts
```

Then at the end of the `api_indexer_health` endpoint, after building the response data but before returning, add:

```python
    # Check for budget alerts and fire notifications
    alerts = _check_budget_alerts(indexer_list)
    if alerts:
        try:
            from splintarr.core.security import decrypt_field
            from splintarr.models.notification import NotificationConfig
            from splintarr.services.discord import DiscordNotificationService

            config = (
                db.query(NotificationConfig)
                .filter(NotificationConfig.is_active.is_(True))
                .first()
            )
            if config and config.is_event_enabled("budget_alert"):
                webhook_url = decrypt_field(config.webhook_url)
                service = DiscordNotificationService(webhook_url)
                for alert in alerts:
                    await service.send_budget_alert(**alert)
        except Exception as e:
            logger.warning("budget_alert_notification_failed", error=str(e))
```

**Step 4: Run tests**

```bash
.venv/bin/python -m pytest tests/unit/test_budget_alert_dedup.py -v --no-cov
```

**Step 5: Commit**

```bash
git add src/splintarr/api/dashboard.py tests/unit/test_budget_alert_dedup.py
git commit -m "feat: fire budget alert notifications with per-period dedup

Alerts at 80%+ usage, once per indexer per budget period.
Wired into /api/dashboard/indexer-health endpoint."
```

---

### Task 4: Smart Batch Auto-Sizing — Model + Schema

**Files:**
- Modify: `src/splintarr/models/search_queue.py:182-183` (add `budget_aware` column)
- Modify: `src/splintarr/schemas/search.py` (add field to Create, Update, Response schemas)

**Step 1: Add `budget_aware` column to SearchQueue model**

After `season_pack_threshold` (line 182), before `created_at` (line 185):

```python
    # Budget-aware batch sizing (v1.3.0)
    budget_aware = Column(
        Boolean,
        default=True,
        nullable=False,
        comment="Automatically reduce batch size when indexer budget is low",
    )
```

**Step 2: Add to Pydantic schemas**

In `SearchQueueCreate`, after `season_pack_threshold`:
```python
    budget_aware: bool = Field(
        default=True,
        description="Automatically reduce batch size when indexer budget is low",
    )
```

In `SearchQueueUpdate`, after `season_pack_threshold`:
```python
    budget_aware: bool | None = Field(
        default=None,
        description="Automatically reduce batch size when indexer budget is low",
    )
```

In `SearchQueueResponse`, after `season_pack_threshold`:
```python
    budget_aware: bool = Field(default=True, description="Budget-aware batch sizing enabled")
```

**Step 3: Commit**

```bash
git add src/splintarr/models/search_queue.py src/splintarr/schemas/search.py
git commit -m "feat: add budget_aware column to SearchQueue model and schemas

Default True — queues automatically reduce batch size when indexer
budget is low. Column auto-created on startup."
```

---

### Task 5: Smart Batch Auto-Sizing — Execution Logic

**Files:**
- Modify: `src/splintarr/services/search_queue.py:195-238` (enhance rate limit block)

**Step 1: Write the test**

Add to `tests/unit/test_budget_aware.py`:

```python
"""Tests for budget-aware batch auto-sizing."""
import pytest


class TestBudgetAwareSizing:
    """Test that budget_aware queues reduce batch size proportionally."""

    def test_budget_aware_reduces_below_20_percent(self):
        """When remaining budget is <20% of limit, cap effective_max."""
        queue_max = 50
        remaining_budget = 8  # 8 of 100 remaining = 8%
        total_limit = 100

        # budget_aware logic: if remaining < 20% of total, use remaining
        if remaining_budget < total_limit * 0.2:
            effective = min(queue_max, remaining_budget)
        else:
            effective = min(queue_max, remaining_budget)

        assert effective == 8

    def test_budget_aware_no_reduction_above_20_percent(self):
        """When remaining budget is >20%, use normal min(queue_max, budget)."""
        queue_max = 50
        remaining_budget = 30  # 30 of 100 = 30%

        effective = min(queue_max, remaining_budget)
        assert effective == 30

    def test_budget_aware_disabled_uses_queue_max(self):
        """When budget_aware=False, ignore Prowlarr budget."""
        queue_max = 50
        remaining_budget = 5

        # budget_aware=False: use queue max regardless
        effective = queue_max
        assert effective == 50
```

**Step 2: Modify execution logic**

In `search_queue.py`, the existing block at line 195-238 already does:
```python
if rate_result["max_items"] is not None:
    effective_max = min(queue.max_items_per_run or 50, rate_result["max_items"])
```

Change to respect `budget_aware`:

```python
            if rate_result["max_items"] is not None:
                budget_aware = getattr(queue, "budget_aware", True)
                if budget_aware:
                    effective_max = min(queue.max_items_per_run or 50, rate_result["max_items"])
                else:
                    effective_max = queue.max_items_per_run or 50
                    logger.debug(
                        "search_queue_budget_aware_disabled",
                        queue_id=queue_id,
                        queue_max=queue.max_items_per_run,
                        prowlarr_budget=rate_result["max_items"],
                    )
```

The budget=0 early return block stays — even with `budget_aware=False`, we still skip if there's literally zero budget (that's a hard stop, not a preference).

**Step 3: Run tests**

```bash
.venv/bin/python -m pytest tests/unit/test_budget_aware.py -v --no-cov
```

**Step 4: Commit**

```bash
git add src/splintarr/services/search_queue.py tests/unit/test_budget_aware.py
git commit -m "feat: respect budget_aware toggle in search execution

When budget_aware=False, queue uses its configured max_items_per_run
regardless of Prowlarr remaining budget. Budget exhaustion (0 remaining)
still causes skip regardless of toggle."
```

---

### Task 6: Smart Batch Auto-Sizing — Queue Modal UI

**Files:**
- Modify: `src/splintarr/templates/dashboard/search_queues.html` (add checkbox to create/edit modal)

**Step 1: Add checkbox to the queue creation modal**

After the season pack section, add:

```html
<label>
    <input type="checkbox" id="budget_aware" name="budget_aware" checked>
    Adjust batch size based on indexer budget
    <small style="display:block;color:var(--muted-color);">When enabled, reduces items per run when indexer API budget is low</small>
</label>
```

**Step 2: Wire into form submission JS**

Add `budget_aware: document.getElementById('budget_aware').checked` to the create and edit form payloads.

**Step 3: Wire into edit modal pre-population**

When editing a queue, set: `document.getElementById('budget_aware').checked = queue.budget_aware !== false;`

**Step 4: Commit**

```bash
git add src/splintarr/templates/dashboard/search_queues.html
git commit -m "feat: add budget-aware toggle to queue creation/edit modal

Checkbox 'Adjust batch size based on indexer budget' defaults to
checked. Pre-populated when editing existing queues."
```

---

### Task 7: Integration Test

**Files:**
- Create: `tests/integration/test_indexer_budget_visibility.py`

**Step 1: Write integration tests covering the full flow**

```python
"""Integration tests for indexer budget visibility feature."""
import pytest
from unittest.mock import AsyncMock, patch

from splintarr.api.dashboard import _check_budget_alerts, _alerted_indexers


class TestBudgetAlertIntegration:
    """Test budget alerts fire correctly from indexer health data."""

    def setup_method(self):
        _alerted_indexers.clear()

    def test_multiple_indexers_only_high_ones_alert(self):
        alerts = _check_budget_alerts([
            {"name": "NZBgeek", "query_limit": 100, "queries_used": 85, "limits_unit": "day"},
            {"name": "DogNZB", "query_limit": 50, "queries_used": 10, "limits_unit": "day"},
            {"name": "NZBFinder", "query_limit": 200, "queries_used": 180, "limits_unit": "day"},
        ])
        assert len(alerts) == 2
        names = [a["indexer_name"] for a in alerts]
        assert "NZBgeek" in names
        assert "NZBFinder" in names
        assert "DogNZB" not in names

    def test_different_units_tracked_separately(self):
        _check_budget_alerts([
            {"name": "NZBgeek", "query_limit": 100, "queries_used": 85, "limits_unit": "day"},
        ])
        # Same indexer but hourly limit — should alert separately
        alerts = _check_budget_alerts([
            {"name": "NZBgeek", "query_limit": 10, "queries_used": 9, "limits_unit": "hour"},
        ])
        assert len(alerts) == 1

    def test_exact_threshold_triggers_alert(self):
        alerts = _check_budget_alerts([
            {"name": "NZBgeek", "query_limit": 100, "queries_used": 80, "limits_unit": "day"},
        ])
        assert len(alerts) == 1
```

**Step 2: Run all tests**

```bash
.venv/bin/python -m pytest tests/unit/test_budget_alert_notification.py tests/unit/test_budget_alert_dedup.py tests/unit/test_budget_aware.py tests/integration/test_indexer_budget_visibility.py -v --no-cov
```

**Step 3: Commit**

```bash
git add tests/integration/test_indexer_budget_visibility.py
git commit -m "test: add integration tests for indexer budget visibility"
```

---

### Task 8: Lint, Type Check, Final Verification

**Step 1: Run linter on all modified files**

```bash
.venv/bin/ruff check src/splintarr/services/discord.py src/splintarr/api/dashboard.py \
  src/splintarr/models/search_queue.py src/splintarr/models/notification.py \
  src/splintarr/schemas/search.py src/splintarr/services/search_queue.py \
  src/splintarr/templates/dashboard/settings.html
```

**Step 2: Run full unit test suite**

```bash
.venv/bin/python -m pytest tests/unit/ --no-cov -q
```

Verify no new failures beyond pre-existing ones.

**Step 3: Fix any issues and commit**

```bash
git commit -m "chore: lint and type fixes for indexer budget visibility"
```
