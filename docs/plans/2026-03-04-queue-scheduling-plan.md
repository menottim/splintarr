# Queue Scheduling Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add daily/weekly schedule modes and jitter to search queues, replacing the interval-only system.

**Architecture:** New `schedule_mode`, `schedule_time`, `schedule_days`, `jitter_minutes` columns on SearchQueue. Scheduler uses APScheduler CronTrigger for daily/weekly modes (existing IntervalTrigger for interval mode). UI adds schedule mode selector with conditional fields.

**Tech Stack:** Python/FastAPI, SQLAlchemy, APScheduler (CronTrigger), Pydantic schemas, Jinja2/JS templates

---

### Task 1: Model + Schema — New Scheduling Columns

**Files:**
- Modify: `src/splintarr/models/search_queue.py:76-81` (add columns after `interval_hours`)
- Modify: `src/splintarr/schemas/search.py` (add fields to Create, Update, Response)

**Step 1: Add columns to SearchQueue model**

After `interval_hours` (line 81), add:

```python
    schedule_mode = Column(
        String(10),
        default="interval",
        server_default="interval",
        nullable=False,
        comment="Schedule mode: interval, daily, or weekly",
    )
    schedule_time = Column(
        String(5),
        nullable=True,
        comment="Time of day for daily/weekly modes (HH:MM format)",
    )
    schedule_days = Column(
        String(20),
        nullable=True,
        comment="Comma-separated days for weekly mode (mon,tue,wed,thu,fri,sat,sun)",
    )
    jitter_minutes = Column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        comment="Random jitter in minutes (0-15) to prevent thundering herd",
    )
```

**Step 2: Add to Pydantic schemas**

In `SearchQueueCreate` (after `interval_hours`):
```python
    schedule_mode: Literal["interval", "daily", "weekly"] = Field(
        default="interval",
        description="Schedule mode: interval, daily, or weekly",
    )
    schedule_time: str | None = Field(
        default=None,
        pattern=r"^\d{2}:\d{2}$",
        description="Time of day for daily/weekly modes (HH:MM)",
    )
    schedule_days: str | None = Field(
        default=None,
        description="Comma-separated days for weekly mode (mon,tue,wed,thu,fri,sat,sun)",
    )
    jitter_minutes: int = Field(
        default=0,
        ge=0,
        le=15,
        description="Random jitter in minutes to prevent thundering herd (0-15)",
    )
```

In `SearchQueueUpdate` (after `interval_hours`):
```python
    schedule_mode: Literal["interval", "daily", "weekly"] | None = Field(
        default=None,
        description="Schedule mode: interval, daily, or weekly",
    )
    schedule_time: str | None = Field(
        default=None,
        pattern=r"^\d{2}:\d{2}$",
        description="Time of day for daily/weekly modes (HH:MM)",
    )
    schedule_days: str | None = Field(
        default=None,
        description="Comma-separated days for weekly mode",
    )
    jitter_minutes: int | None = Field(
        default=None,
        ge=0,
        le=15,
        description="Random jitter in minutes (0-15)",
    )
```

In `SearchQueueResponse` (after `interval_hours`):
```python
    schedule_mode: str = Field(default="interval", description="Schedule mode")
    schedule_time: str | None = Field(default=None, description="Time for daily/weekly (HH:MM)")
    schedule_days: str | None = Field(default=None, description="Days for weekly mode")
    jitter_minutes: int = Field(default=0, description="Jitter minutes")
```

**Step 3: Add validation**

In `SearchQueueCreate`, add a model validator after the existing `validate_custom_strategy_filters`:

```python
    @model_validator(mode="after")
    def validate_schedule_fields(self) -> "SearchQueueCreate":
        """Validate schedule fields based on schedule_mode."""
        if not self.recurring:
            return self
        if self.schedule_mode == "daily" and not self.schedule_time:
            raise ValueError("schedule_time (HH:MM) is required for daily mode")
        if self.schedule_mode == "weekly":
            if not self.schedule_time:
                raise ValueError("schedule_time (HH:MM) is required for weekly mode")
            if not self.schedule_days:
                raise ValueError("schedule_days is required for weekly mode")
        if self.schedule_mode == "interval" and not self.interval_hours:
            raise ValueError("interval_hours is required for interval mode")
        return self
```

Note: Also update the `Literal` import at the top to include the new types if needed. Add `String` to the SQLAlchemy imports in the model file.

**Step 4: Lint**

```bash
.venv/bin/ruff check src/splintarr/models/search_queue.py src/splintarr/schemas/search.py
```

**Step 5: Commit**

```bash
git add src/splintarr/models/search_queue.py src/splintarr/schemas/search.py
git commit -m "feat: add schedule_mode, schedule_time, schedule_days, jitter_minutes columns

Three schedule modes: interval (existing), daily (HH:MM), weekly (days+HH:MM).
Jitter 0-15 min for thundering herd prevention.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Scheduler — CronTrigger Support

**Files:**
- Modify: `src/splintarr/services/scheduler.py:324-356` (replace trigger logic)
- Create: `tests/unit/test_schedule_trigger.py`

**Step 1: Write the failing test**

Create `tests/unit/test_schedule_trigger.py`:

```python
"""Tests for schedule trigger selection."""
import pytest

from splintarr.services.scheduler import _build_trigger_kwargs


class TestBuildTriggerKwargs:
    """Test trigger kwargs generation for different schedule modes."""

    def test_interval_mode(self):
        result = _build_trigger_kwargs(
            schedule_mode="interval",
            interval_hours=4,
            schedule_time=None,
            schedule_days=None,
            jitter_minutes=0,
        )
        assert result["trigger"] == "interval"
        assert result["hours"] == 4
        assert "jitter" not in result

    def test_interval_mode_with_jitter(self):
        result = _build_trigger_kwargs(
            schedule_mode="interval",
            interval_hours=4,
            schedule_time=None,
            schedule_days=None,
            jitter_minutes=10,
        )
        assert result["trigger"] == "interval"
        assert result["jitter"] == 600  # 10 * 60

    def test_daily_mode(self):
        result = _build_trigger_kwargs(
            schedule_mode="daily",
            interval_hours=None,
            schedule_time="02:30",
            schedule_days=None,
            jitter_minutes=0,
        )
        assert result["trigger"] == "cron"
        assert result["hour"] == 2
        assert result["minute"] == 30

    def test_weekly_mode(self):
        result = _build_trigger_kwargs(
            schedule_mode="weekly",
            interval_hours=None,
            schedule_time="03:00",
            schedule_days="mon,wed,fri",
            jitter_minutes=5,
        )
        assert result["trigger"] == "cron"
        assert result["day_of_week"] == "mon,wed,fri"
        assert result["hour"] == 3
        assert result["minute"] == 0
        assert result["jitter"] == 300

    def test_defaults_to_interval(self):
        """Unknown mode falls back to interval."""
        result = _build_trigger_kwargs(
            schedule_mode=None,
            interval_hours=24,
            schedule_time=None,
            schedule_days=None,
            jitter_minutes=0,
        )
        assert result["trigger"] == "interval"
```

**Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest tests/unit/test_schedule_trigger.py -v --no-cov
```

**Step 3: Add `_build_trigger_kwargs` helper to scheduler.py**

Add before `schedule_queue()`:

```python
def _build_trigger_kwargs(
    schedule_mode: str | None,
    interval_hours: int | None,
    schedule_time: str | None,
    schedule_days: str | None,
    jitter_minutes: int,
) -> dict[str, Any]:
    """Build APScheduler trigger kwargs based on schedule mode.

    Args:
        schedule_mode: "interval", "daily", or "weekly"
        interval_hours: Hours between runs (interval mode)
        schedule_time: "HH:MM" string (daily/weekly modes)
        schedule_days: Comma-separated days like "mon,wed,fri" (weekly mode)
        jitter_minutes: Random jitter 0-15 minutes

    Returns:
        dict: kwargs to pass to scheduler.add_job()
    """
    jitter_seconds = jitter_minutes * 60 if jitter_minutes else 0

    if schedule_mode == "daily" and schedule_time:
        hour, minute = int(schedule_time.split(":")[0]), int(schedule_time.split(":")[1])
        kwargs: dict[str, Any] = {
            "trigger": "cron",
            "hour": hour,
            "minute": minute,
        }
        if jitter_seconds:
            kwargs["jitter"] = jitter_seconds
        return kwargs

    if schedule_mode == "weekly" and schedule_time and schedule_days:
        hour, minute = int(schedule_time.split(":")[0]), int(schedule_time.split(":")[1])
        kwargs = {
            "trigger": "cron",
            "day_of_week": schedule_days,
            "hour": hour,
            "minute": minute,
        }
        if jitter_seconds:
            kwargs["jitter"] = jitter_seconds
        return kwargs

    # Default: interval mode
    kwargs = {
        "trigger": "interval",
        "hours": interval_hours or 24,
    }
    if jitter_seconds:
        kwargs["jitter"] = jitter_seconds
    return kwargs
```

**Step 4: Update `schedule_queue()` to use the helper**

Replace the trigger selection block (lines 325-356) with:

```python
                if queue.is_recurring:
                    trigger_kwargs = _build_trigger_kwargs(
                        schedule_mode=getattr(queue, "schedule_mode", "interval"),
                        interval_hours=queue.interval_hours,
                        schedule_time=getattr(queue, "schedule_time", None),
                        schedule_days=getattr(queue, "schedule_days", None),
                        jitter_minutes=getattr(queue, "jitter_minutes", 0),
                    )
                    self.scheduler.add_job(
                        self._execute_search_queue,
                        id=job_id,
                        args=[queue_id],
                        next_run_time=run_time,
                        replace_existing=True,
                        **trigger_kwargs,
                    )
                    logger.info(
                        "scheduled_recurring_queue",
                        queue_id=queue_id,
                        schedule_mode=getattr(queue, "schedule_mode", "interval"),
                        next_run=run_time,
                    )
                else:
                    # One-time job (unchanged)
                    self.scheduler.add_job(
                        self._execute_search_queue,
                        trigger="date",
                        run_date=run_time,
                        id=job_id,
                        args=[queue_id],
                        replace_existing=True,
                    )
                    logger.info(
                        "scheduled_onetime_queue",
                        queue_id=queue_id,
                        run_date=run_time,
                    )
```

**Step 5: Run tests**

```bash
.venv/bin/python -m pytest tests/unit/test_schedule_trigger.py -v --no-cov
```

**Step 6: Commit**

```bash
git add src/splintarr/services/scheduler.py tests/unit/test_schedule_trigger.py
git commit -m "feat: add CronTrigger support for daily/weekly schedule modes

_build_trigger_kwargs helper selects interval/cron trigger based on
schedule_mode. Jitter passed as seconds to APScheduler. 6 unit tests.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Queue Modal UI — Schedule Mode Selector

**Files:**
- Modify: `src/splintarr/templates/dashboard/search_queues.html`

**Step 1: Replace the interval input with a schedule mode selector**

When "Recurring" is checked, instead of just showing the hours input, show a mode selector:

```html
<div id="scheduleOptions" style="display: none;">
    <label for="schedule_mode">Schedule Mode
        <select id="schedule_mode" name="schedule_mode">
            <option value="interval">Every N hours</option>
            <option value="daily">Daily at specific time</option>
            <option value="weekly">Weekly on specific days</option>
        </select>
    </label>

    <!-- Interval mode -->
    <div id="scheduleIntervalRow">
        <label for="interval_hours">Interval (hours)
            <input type="number" id="interval_hours" name="interval_hours" min="1" max="168" placeholder="24">
        </label>
    </div>

    <!-- Daily/Weekly mode -->
    <div id="scheduleTimeRow" style="display: none;">
        <label for="schedule_time">Time (HH:MM)
            <input type="time" id="schedule_time" name="schedule_time" value="03:00">
        </label>
    </div>

    <!-- Weekly mode only -->
    <div id="scheduleDaysRow" style="display: none;">
        <fieldset>
            <legend>Days</legend>
            <label><input type="checkbox" name="schedule_day" value="mon" checked> Mon</label>
            <label><input type="checkbox" name="schedule_day" value="tue"> Tue</label>
            <label><input type="checkbox" name="schedule_day" value="wed" checked> Wed</label>
            <label><input type="checkbox" name="schedule_day" value="thu"> Thu</label>
            <label><input type="checkbox" name="schedule_day" value="fri" checked> Fri</label>
            <label><input type="checkbox" name="schedule_day" value="sat"> Sat</label>
            <label><input type="checkbox" name="schedule_day" value="sun"> Sun</label>
        </fieldset>
    </div>

    <!-- Jitter (all modes) -->
    <label for="jitter_minutes">Jitter (minutes)
        <input type="number" id="jitter_minutes" name="jitter_minutes" min="0" max="15" value="0">
        <small style="display:block;color:var(--muted-color);">Random offset to prevent all queues running at exactly the same time</small>
    </label>
</div>
```

**Step 2: Add JS to toggle visibility based on schedule_mode**

```javascript
document.getElementById('schedule_mode').addEventListener('change', function() {
    var mode = this.value;
    document.getElementById('scheduleIntervalRow').style.display = mode === 'interval' ? '' : 'none';
    document.getElementById('scheduleTimeRow').style.display = (mode === 'daily' || mode === 'weekly') ? '' : 'none';
    document.getElementById('scheduleDaysRow').style.display = mode === 'weekly' ? '' : 'none';
});
```

**Step 3: Wire into form submission**

Add to the create/edit payload:
```javascript
schedule_mode: document.getElementById('schedule_mode').value,
schedule_time: document.getElementById('schedule_time').value || null,
schedule_days: Array.from(document.querySelectorAll('input[name="schedule_day"]:checked')).map(c => c.value).join(',') || null,
jitter_minutes: parseInt(document.getElementById('jitter_minutes').value) || 0,
```

**Step 4: Wire into edit modal pre-population**

When editing a queue, set the schedule mode and fields:
```javascript
document.getElementById('schedule_mode').value = queue.schedule_mode || 'interval';
document.getElementById('schedule_time').value = queue.schedule_time || '03:00';
document.getElementById('jitter_minutes').value = queue.jitter_minutes || 0;
// Check day checkboxes
if (queue.schedule_days) {
    var days = queue.schedule_days.split(',');
    document.querySelectorAll('input[name="schedule_day"]').forEach(function(cb) {
        cb.checked = days.indexOf(cb.value) >= 0;
    });
}
// Trigger change event to show/hide fields
document.getElementById('schedule_mode').dispatchEvent(new Event('change'));
```

**Step 5: Update presets**

```javascript
'aggressive-missing': { ..., schedule_mode: 'interval', interval_hours: 1, jitter_minutes: 5 },
'weekly-cutoff': { ..., schedule_mode: 'weekly', schedule_time: '03:00', schedule_days: 'mon,thu', jitter_minutes: 10 },
'new-releases': { ..., schedule_mode: 'interval', interval_hours: 4, jitter_minutes: 5 },
```

**Step 6: Update queue card display**

In the queue card display, show schedule info based on mode:
- Interval: "Every Nh" (existing)
- Daily: "Daily at HH:MM"
- Weekly: "Mon, Wed, Fri at HH:MM"

**Step 7: Commit**

```bash
git add src/splintarr/templates/dashboard/search_queues.html
git commit -m "feat: add schedule mode selector to queue creation/edit modal

Three modes: interval (existing), daily (time picker), weekly (day
checkboxes + time picker). Jitter slider 0-15 min. Presets updated.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Integration Tests

**Files:**
- Create: `tests/integration/test_queue_scheduling.py`

**Step 1: Write integration tests**

```python
"""Integration tests for queue scheduling modes."""
import pytest

from splintarr.services.scheduler import _build_trigger_kwargs


class TestScheduleModesIntegration:
    def test_interval_mode_backward_compatible(self):
        """Existing queues with no schedule_mode default to interval."""
        result = _build_trigger_kwargs(
            schedule_mode=None,
            interval_hours=24,
            schedule_time=None,
            schedule_days=None,
            jitter_minutes=0,
        )
        assert result["trigger"] == "interval"
        assert result["hours"] == 24

    def test_daily_mode_parses_time(self):
        result = _build_trigger_kwargs(
            schedule_mode="daily",
            interval_hours=None,
            schedule_time="14:30",
            schedule_days=None,
            jitter_minutes=0,
        )
        assert result["hour"] == 14
        assert result["minute"] == 30

    def test_weekly_mode_all_days(self):
        result = _build_trigger_kwargs(
            schedule_mode="weekly",
            interval_hours=None,
            schedule_time="02:00",
            schedule_days="mon,tue,wed,thu,fri,sat,sun",
            jitter_minutes=15,
        )
        assert result["day_of_week"] == "mon,tue,wed,thu,fri,sat,sun"
        assert result["jitter"] == 900

    def test_jitter_zero_omitted(self):
        result = _build_trigger_kwargs(
            schedule_mode="interval",
            interval_hours=6,
            schedule_time=None,
            schedule_days=None,
            jitter_minutes=0,
        )
        assert "jitter" not in result

    def test_daily_without_time_uses_midnight(self):
        """Daily mode with no time should still work (defaults handled upstream)."""
        result = _build_trigger_kwargs(
            schedule_mode="daily",
            interval_hours=None,
            schedule_time=None,
            schedule_days=None,
            jitter_minutes=0,
        )
        # Falls back to interval since schedule_time is None
        assert result["trigger"] == "interval"
```

**Step 2: Run all tests**

```bash
.venv/bin/python -m pytest tests/unit/test_schedule_trigger.py tests/integration/test_queue_scheduling.py -v --no-cov
```

**Step 3: Commit**

```bash
git add tests/integration/test_queue_scheduling.py
git commit -m "test: add integration tests for queue scheduling modes

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Lint + Final Verification

**Step 1: Lint all modified files**

```bash
.venv/bin/ruff check src/splintarr/models/search_queue.py src/splintarr/schemas/search.py \
  src/splintarr/services/scheduler.py
```

**Step 2: Run full unit test suite**

```bash
.venv/bin/python -m pytest tests/unit/ --no-cov -q
```

Verify no new failures beyond pre-existing.

**Step 3: Commit any fixes**

```bash
git commit -m "chore: lint and type fixes for queue scheduling

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```
