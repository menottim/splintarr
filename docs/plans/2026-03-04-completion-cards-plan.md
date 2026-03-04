# Completion Cards Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add "Completion Progress" cards to the dashboard and Library page showing most incomplete, closest to complete, and recently aired incomplete series.

**Architecture:** New `/api/library/completion` endpoint returns 3 sorted lists. Dashboard card fetches via JS on load. Library page renders a collapsible section above the poster grid. All data from existing LibraryItem model — no DB changes.

**Tech Stack:** Python/FastAPI, SQLAlchemy queries, Jinja2 templates, Pico CSS, vanilla JS

---

### Task 1: Completion API Endpoint

**Files:**
- Modify: `src/splintarr/api/library.py` (add new endpoint)
- Create: `tests/unit/test_completion_api.py`

**Step 1: Write the failing test**

Create `tests/unit/test_completion_api.py`:

```python
"""Tests for /api/library/completion endpoint."""
import pytest
from unittest.mock import MagicMock, patch

from splintarr.api.library import _get_completion_data


class TestGetCompletionData:
    """Test _get_completion_data returns sorted completion lists."""

    def test_most_incomplete_sorted_ascending(self):
        """Items sorted by completion_pct ASC (most incomplete first)."""
        items = [
            MagicMock(id=1, title="A", year=2020, episode_count=10, episode_have=8,
                      poster_path="a.jpg", status="ended"),
            MagicMock(id=2, title="B", year=2021, episode_count=50, episode_have=5,
                      poster_path="b.jpg", status="continuing"),
            MagicMock(id=3, title="C", year=2022, episode_count=20, episode_have=20,
                      poster_path="c.jpg", status="ended"),
        ]
        # Mock completion_pct property
        type(items[0]).completion_pct = property(lambda self: 80.0)
        type(items[1]).completion_pct = property(lambda self: 10.0)
        type(items[2]).completion_pct = property(lambda self: 100.0)

        result = _get_completion_data(items)

        # Most incomplete: only incomplete items, sorted ascending
        assert len(result["most_incomplete"]) == 2
        assert result["most_incomplete"][0]["title"] == "B"  # 10%
        assert result["most_incomplete"][1]["title"] == "A"  # 80%

    def test_closest_to_complete_sorted_descending(self):
        """Items >= 50% and < 100% sorted by completion_pct DESC."""
        items = [
            MagicMock(id=1, title="A", year=2020, episode_count=10, episode_have=6,
                      poster_path="a.jpg", status="ended"),
            MagicMock(id=2, title="B", year=2021, episode_count=10, episode_have=9,
                      poster_path="b.jpg", status="continuing"),
            MagicMock(id=3, title="C", year=2022, episode_count=10, episode_have=2,
                      poster_path="c.jpg", status="ended"),
        ]
        type(items[0]).completion_pct = property(lambda self: 60.0)
        type(items[1]).completion_pct = property(lambda self: 90.0)
        type(items[2]).completion_pct = property(lambda self: 20.0)

        result = _get_completion_data(items)

        # Closest to complete: >= 50%, < 100%, sorted DESC
        assert len(result["closest_to_complete"]) == 2
        assert result["closest_to_complete"][0]["title"] == "B"  # 90%
        assert result["closest_to_complete"][1]["title"] == "A"  # 60%

    def test_complete_items_excluded(self):
        """100% complete items don't appear in any list."""
        items = [
            MagicMock(id=1, title="Complete", year=2020, episode_count=10,
                      episode_have=10, poster_path="a.jpg", status="ended"),
        ]
        type(items[0]).completion_pct = property(lambda self: 100.0)

        result = _get_completion_data(items)

        assert len(result["most_incomplete"]) == 0
        assert len(result["closest_to_complete"]) == 0
        assert len(result["recently_aired"]) == 0

    def test_lists_limited_to_10(self):
        """Each list returns at most 10 items."""
        items = []
        for i in range(15):
            m = MagicMock(id=i, title=f"S{i}", year=2020, episode_count=100,
                          episode_have=i*5, poster_path=f"{i}.jpg", status="continuing",
                          added_at="2025-01-01")
            type(m).completion_pct = property(lambda self, i=i: i * 5.0)
            items.append(m)

        result = _get_completion_data(items)

        assert len(result["most_incomplete"]) <= 10
```

**Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest tests/unit/test_completion_api.py -v --no-cov
```

Expected: FAIL — `_get_completion_data` does not exist.

**Step 3: Implement `_get_completion_data` and `/api/library/completion` endpoint**

In `src/splintarr/api/library.py`, add the helper function after `_base_library_query`:

```python
def _get_completion_data(items: list) -> dict[str, list[dict]]:
    """Build sorted completion lists from LibraryItem objects.

    Returns:
        dict with most_incomplete, closest_to_complete, recently_aired lists.
    """
    def _item_dict(item) -> dict:
        return {
            "id": item.id,
            "title": item.title,
            "year": item.year,
            "episode_count": item.episode_count,
            "episode_have": item.episode_have,
            "completion_pct": round(item.completion_pct, 1),
            "poster_path": item.poster_path,
            "status": item.status,
        }

    incomplete = [i for i in items if i.episode_count > 0 and i.episode_have < i.episode_count]

    most_incomplete = sorted(incomplete, key=lambda i: i.completion_pct)[:10]
    closest_to_complete = sorted(
        [i for i in incomplete if i.completion_pct >= 50],
        key=lambda i: i.completion_pct,
        reverse=True,
    )[:10]
    recently_aired = sorted(
        incomplete,
        key=lambda i: i.added_at or "",
        reverse=True,
    )[:10]

    return {
        "most_incomplete": [_item_dict(i) for i in most_incomplete],
        "closest_to_complete": [_item_dict(i) for i in closest_to_complete],
        "recently_aired": [_item_dict(i) for i in recently_aired],
    }
```

Then add the endpoint:

```python
@router.get("/api/library/completion", include_in_schema=False)
@limiter.limit("30/minute")
async def api_library_completion(
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Completion progress data for dashboard and library page."""
    items = _base_library_query(db, current_user).all()

    logger.debug(
        "library_completion_data_requested",
        user_id=current_user.id,
        total_items=len(items),
    )

    return JSONResponse(content=_get_completion_data(items))
```

**Step 4: Run tests**

```bash
.venv/bin/python -m pytest tests/unit/test_completion_api.py -v --no-cov
```

**Step 5: Commit**

```bash
git add src/splintarr/api/library.py tests/unit/test_completion_api.py
git commit -m "feat: add /api/library/completion endpoint

Returns 3 sorted lists: most_incomplete, closest_to_complete,
recently_aired. Max 10 items each.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Dashboard Completion Card

**Files:**
- Modify: `src/splintarr/templates/dashboard/index.html` (add card HTML + JS)

**Step 1: Add the card HTML**

Insert after the analytics card closing `</article>` (around line 168) and before the indexer health section (line 171):

```html
<!-- Completion Progress -->
<article id="completion-card" style="display: none;">
    <header>
        <h3>Completion Progress</h3>
    </header>
    <div id="completion-tabs" style="margin-bottom: 0.75rem;">
        <small>
            <a href="#" data-completion-tab="most_incomplete" class="completion-tab-active" style="margin-right: 0.75rem; font-weight: 600;">Most Incomplete</a>
            <a href="#" data-completion-tab="closest_to_complete" style="margin-right: 0.75rem; color: var(--muted-color);">Closest to Complete</a>
            <a href="#" data-completion-tab="recently_aired" style="color: var(--muted-color);">Recently Aired</a>
        </small>
    </div>
    <div id="completion-list"></div>
    <div style="margin-top: 0.5rem;">
        <small><a href="/dashboard/library">View full library</a></small>
    </div>
</article>
```

**Step 2: Add the JS to load and render completion data**

In the `extra_scripts` block, add:

```javascript
// Completion Progress card
(async function() {
    try {
        var response = await fetch('/api/library/completion');
        if (!response.ok) return;
        var data = await response.json();

        // Store data for tab switching
        window._completionData = data;

        var card = document.getElementById('completion-card');
        if (!card) return;

        // Check if any data exists
        var hasData = data.most_incomplete.length > 0 ||
                      data.closest_to_complete.length > 0 ||
                      data.recently_aired.length > 0;
        if (!hasData) return;

        card.style.display = '';
        renderCompletionList(data.most_incomplete);

        // Tab click handlers
        document.querySelectorAll('[data-completion-tab]').forEach(function(tab) {
            tab.addEventListener('click', function(e) {
                e.preventDefault();
                var key = this.dataset.completionTab;
                renderCompletionList(window._completionData[key]);
                // Update active tab styling
                document.querySelectorAll('[data-completion-tab]').forEach(function(t) {
                    t.style.fontWeight = '';
                    t.style.color = 'var(--muted-color)';
                    t.classList.remove('completion-tab-active');
                });
                this.style.fontWeight = '600';
                this.style.color = '';
                this.classList.add('completion-tab-active');
            });
        });
    } catch (e) { /* ignore */ }
})();

function renderCompletionList(items) {
    var container = document.getElementById('completion-list');
    if (!container) return;
    container.textContent = '';

    if (!items || items.length === 0) {
        var empty = document.createElement('small');
        empty.style.color = 'var(--muted-color)';
        empty.textContent = 'No items in this category';
        container.appendChild(empty);
        return;
    }

    items.slice(0, 5).forEach(function(item) {
        var row = document.createElement('a');
        row.href = '/dashboard/library/' + item.id;
        row.style.cssText = 'display:flex;align-items:center;gap:0.5rem;padding:0.35rem 0;text-decoration:none;color:inherit;border-bottom:1px solid var(--muted-border-color);';

        // Poster thumbnail
        var img = document.createElement('img');
        img.src = item.poster_path ? '/posters/' + item.poster_path : '';
        img.alt = '';
        img.style.cssText = 'width:32px;height:48px;object-fit:cover;border-radius:3px;background:var(--muted-border-color);';
        img.onerror = function() { this.style.display = 'none'; };
        row.appendChild(img);

        // Info
        var info = document.createElement('div');
        info.style.cssText = 'flex:1;min-width:0;';

        var title = document.createElement('div');
        title.style.cssText = 'font-size:0.85rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
        title.textContent = item.title + (item.year ? ' (' + item.year + ')' : '');
        info.appendChild(title);

        // Progress bar
        var barOuter = document.createElement('div');
        barOuter.style.cssText = 'background:var(--muted-border-color);border-radius:3px;height:6px;width:100%;margin-top:2px;';
        var barInner = document.createElement('div');
        var pct = item.completion_pct;
        var barColor = pct >= 80 ? 'var(--ins-color)' : pct >= 50 ? 'var(--mark-background-color)' : 'var(--del-color)';
        barInner.style.cssText = 'height:100%;border-radius:3px;background:' + barColor + ';width:' + pct + '%;';
        barOuter.appendChild(barInner);
        info.appendChild(barOuter);

        row.appendChild(info);

        // Count
        var count = document.createElement('small');
        count.style.cssText = 'white-space:nowrap;color:var(--muted-color);';
        count.textContent = item.episode_have + '/' + item.episode_count;
        row.appendChild(count);

        container.appendChild(row);
    });
}
```

**Step 3: Commit**

```bash
git add src/splintarr/templates/dashboard/index.html
git commit -m "feat: add Completion Progress card to dashboard

Fetches /api/library/completion, shows top 5 items per tab.
Three tabs: Most Incomplete, Closest to Complete, Recently Aired.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Library Page Completion Section

**Files:**
- Modify: `src/splintarr/templates/dashboard/library.html` (add section above poster grid)
- Modify: `src/splintarr/api/library.py` (pass completion data to template context)

**Step 1: Pass completion data to Library template**

In the library route handler (in `_render_library_page` or the main `library_overview` handler), add completion data to the template context. Find where the template is rendered and add:

```python
completion_data = _get_completion_data(items)
```

Pass `"completion": completion_data` in the template context dict.

**Step 2: Add collapsible completion section to library.html**

Insert before the poster grid (around line 27), after the filter/action bar:

```html
<!-- Completion Progress Section -->
{% if completion.most_incomplete %}
<details open>
    <summary><strong>Completion Progress</strong></summary>
    <div style="margin-top: 0.5rem;">
        <small>
            <a href="#" data-lib-completion-tab="most_incomplete" class="lib-tab-active" style="margin-right: 0.75rem; font-weight: 600;">Most Incomplete</a>
            <a href="#" data-lib-completion-tab="closest_to_complete" style="margin-right: 0.75rem; color: var(--muted-color);">Closest to Complete</a>
            <a href="#" data-lib-completion-tab="recently_aired" style="color: var(--muted-color);">Recently Aired</a>
        </small>
    </div>
    <div id="lib-completion-list" style="display:flex;gap:0.75rem;overflow-x:auto;padding:0.75rem 0;">
        {% for item in completion.most_incomplete %}
        <a href="/dashboard/library/{{ item.id }}" style="display:flex;flex-direction:column;min-width:120px;max-width:120px;text-decoration:none;color:inherit;">
            <img src="/posters/{{ item.poster_path }}" alt="" style="width:120px;height:170px;object-fit:cover;border-radius:4px;background:var(--muted-border-color);" onerror="this.style.display='none'">
            <small style="margin-top:0.25rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{{ item.title }}</small>
            <div style="background:var(--muted-border-color);border-radius:3px;height:6px;width:100%;margin-top:2px;">
                <div style="height:100%;border-radius:3px;width:{{ item.completion_pct }}%;background:{% if item.completion_pct >= 80 %}var(--ins-color){% elif item.completion_pct >= 50 %}var(--mark-background-color){% else %}var(--del-color){% endif %};"></div>
            </div>
            <small style="color:var(--muted-color);font-size:0.7rem;">{{ item.episode_have }}/{{ item.episode_count }}</small>
        </a>
        {% endfor %}
    </div>
</details>
{% endif %}
```

**Step 3: Add tab-switching JS**

In the library page's `extra_scripts` block, add JS that swaps the `lib-completion-list` content when tabs are clicked, using the completion data passed from the server. Store the data as a JSON script tag or data attributes.

**Step 4: Commit**

```bash
git add src/splintarr/templates/dashboard/library.html src/splintarr/api/library.py
git commit -m "feat: add Completion Progress section to Library page

Collapsible section above poster grid with scrollable cards.
Three tabs: Most Incomplete, Closest to Complete, Recently Aired.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Demo Data for Completion Cards

**Files:**
- Modify: `src/splintarr/services/demo.py` (add completion demo data)

**Step 1: Add `get_demo_completion` function**

```python
def get_demo_completion() -> dict[str, list[dict]]:
    """Synthetic completion data matching /api/library/completion shape."""
    return {
        "most_incomplete": [
            {"id": 1, "title": "The Wire", "year": 2002, "episode_count": 60, "episode_have": 12, "completion_pct": 20.0, "poster_path": None, "status": "ended"},
            {"id": 2, "title": "Lost", "year": 2004, "episode_count": 121, "episode_have": 34, "completion_pct": 28.1, "poster_path": None, "status": "ended"},
            {"id": 3, "title": "The Sopranos", "year": 1999, "episode_count": 86, "episode_have": 30, "completion_pct": 34.9, "poster_path": None, "status": "ended"},
        ],
        "closest_to_complete": [
            {"id": 4, "title": "Breaking Bad", "year": 2008, "episode_count": 62, "episode_have": 58, "completion_pct": 93.5, "poster_path": None, "status": "ended"},
            {"id": 5, "title": "Better Call Saul", "year": 2015, "episode_count": 63, "episode_have": 55, "completion_pct": 87.3, "poster_path": None, "status": "ended"},
        ],
        "recently_aired": [
            {"id": 6, "title": "Severance", "year": 2022, "episode_count": 19, "episode_have": 10, "completion_pct": 52.6, "poster_path": None, "status": "continuing"},
            {"id": 7, "title": "The Last of Us", "year": 2023, "episode_count": 16, "episode_have": 9, "completion_pct": 56.3, "poster_path": None, "status": "continuing"},
        ],
        "demo": True,
    }
```

**Step 2: Wire demo data into dashboard and library endpoints**

In the completion endpoint, check for demo mode and return demo data:

```python
if is_demo_active(db, current_user.id):
    return JSONResponse(content=get_demo_completion())
```

**Step 3: Commit**

```bash
git add src/splintarr/services/demo.py src/splintarr/api/library.py
git commit -m "feat: add demo data for completion cards

Synthetic completion data shown when no real instances configured.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Lint + Final Verification

**Step 1: Lint all modified files**

```bash
.venv/bin/ruff check src/splintarr/api/library.py src/splintarr/services/demo.py
```

**Step 2: Run all completion tests**

```bash
.venv/bin/python -m pytest tests/unit/test_completion_api.py -v --no-cov
```

**Step 3: Run full unit test suite**

```bash
.venv/bin/python -m pytest tests/unit/ --no-cov -q
```

Verify no new failures beyond pre-existing.

**Step 4: Commit any fixes**

```bash
git commit -m "chore: lint and type fixes for completion cards"
```
