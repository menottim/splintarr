# Config Import Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow users to upload a previously exported JSON config file to restore instances, queues, exclusions, and notifications with API key/webhook re-entry.

**Architecture:** New service (`config_import.py`) handles validation and import logic. Two API endpoints: preview (validates + shows conflicts) and apply (atomic import). Settings UI gets file upload + preview modal with secret inputs.

**Tech Stack:** Python/FastAPI, SQLAlchemy transactions, Pydantic validation, Jinja2/JS modal

---

### Task 1: Import Service — Validation + Preview

**Files:**
- Create: `src/splintarr/services/config_import.py`
- Create: `tests/unit/test_config_import.py`

**Step 1: Write the failing test**

```python
"""Tests for config import validation and preview."""
import pytest

from splintarr.services.config_import import validate_import_data


class TestValidateImportData:
    def test_valid_config_returns_preview(self):
        data = {
            "splintarr_version": "1.2.0",
            "exported_at": "2026-03-04T00:00:00",
            "instances": [
                {"name": "My Sonarr", "instance_type": "sonarr", "url": "http://sonarr:8989",
                 "api_key": "[REDACTED]", "is_active": True, "verify_ssl": True,
                 "timeout_seconds": 30, "rate_limit_per_second": 5.0}
            ],
            "search_queues": [
                {"name": "Missing Weekly", "instance_id": 1, "strategy": "missing",
                 "is_recurring": True, "interval_hours": 24, "is_active": True, "filters": None}
            ],
            "exclusions": [],
            "notifications": None,
        }
        result = validate_import_data(data, existing_instance_names=set())
        assert result["valid"] is True
        assert len(result["instances"]) == 1
        assert result["instances"][0]["status"] == "new"
        assert result["instances"][0]["needs_api_key"] is True

    def test_missing_required_keys_invalid(self):
        data = {"splintarr_version": "1.0.0"}
        result = validate_import_data(data, existing_instance_names=set())
        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_duplicate_instance_marked_conflict(self):
        data = {
            "splintarr_version": "1.2.0",
            "exported_at": "2026-03-04T00:00:00",
            "instances": [
                {"name": "Existing", "instance_type": "sonarr", "url": "http://sonarr:8989",
                 "api_key": "[REDACTED]", "is_active": True, "verify_ssl": True,
                 "timeout_seconds": 30, "rate_limit_per_second": 5.0}
            ],
            "search_queues": [],
            "exclusions": [],
            "notifications": None,
        }
        result = validate_import_data(data, existing_instance_names={"Existing"})
        assert result["instances"][0]["status"] == "conflict_skip"
        assert result["instances"][0]["needs_api_key"] is False

    def test_queue_linked_to_conflict_instance_skipped(self):
        data = {
            "splintarr_version": "1.2.0",
            "exported_at": "2026-03-04T00:00:00",
            "instances": [
                {"name": "Existing", "instance_type": "sonarr", "url": "http://sonarr:8989",
                 "api_key": "[REDACTED]", "is_active": True, "verify_ssl": True,
                 "timeout_seconds": 30, "rate_limit_per_second": 5.0}
            ],
            "search_queues": [
                {"name": "Q1", "instance_id": 99, "strategy": "missing",
                 "is_recurring": False, "interval_hours": None, "is_active": True, "filters": None}
            ],
            "exclusions": [],
            "notifications": None,
        }
        # Build instance_id->name mapping from export data
        result = validate_import_data(data, existing_instance_names={"Existing"})
        assert result["queues"][0]["status"] == "skip_instance_conflict"

    def test_notification_needs_webhook(self):
        data = {
            "splintarr_version": "1.2.0",
            "exported_at": "2026-03-04T00:00:00",
            "instances": [],
            "search_queues": [],
            "exclusions": [],
            "notifications": {
                "webhook_url": "[REDACTED]",
                "events_enabled": {"search_triggered": True},
                "is_active": True,
            },
        }
        result = validate_import_data(data, existing_instance_names=set())
        assert result["notifications"]["has_config"] is True
        assert result["notifications"]["needs_webhook"] is True
```

**Step 2: Run test to verify it fails**

**Step 3: Implement `validate_import_data`**

Create `src/splintarr/services/config_import.py`:

```python
"""Config Import Service for Splintarr.

Validates and applies imported configuration files (JSON format matching
the Config Export output). Handles conflict detection, secret re-entry,
and atomic import with rollback on failure.
"""

from typing import Any

import structlog

logger = structlog.get_logger()

REQUIRED_KEYS = {"splintarr_version", "exported_at", "instances", "search_queues", "exclusions"}


def validate_import_data(
    data: dict[str, Any],
    existing_instance_names: set[str],
    existing_has_notifications: bool = False,
) -> dict[str, Any]:
    """Validate import data and return a preview of what will be imported.

    Args:
        data: Parsed JSON from the import file
        existing_instance_names: Set of instance names the user already has
        existing_has_notifications: Whether user already has notification config

    Returns:
        dict with valid, instances, queues, exclusions_count, notifications, errors
    """
    errors: list[str] = []

    # Validate required keys
    missing = REQUIRED_KEYS - set(data.keys())
    if missing:
        return {
            "valid": False,
            "errors": [f"Missing required keys: {', '.join(sorted(missing))}"],
            "instances": [],
            "queues": [],
            "exclusions_count": 0,
            "notifications": {"has_config": False, "needs_webhook": False},
        }

    # Build instance_id -> name mapping from export data
    export_id_to_name: dict[int, str] = {}
    for inst in data.get("instances", []):
        if "id" in inst and "name" in inst:
            export_id_to_name[inst["id"]] = inst["name"]

    # Analyze instances
    instances_preview = []
    new_instance_names: set[str] = set()
    for inst in data.get("instances", []):
        name = inst.get("name", "")
        if name in existing_instance_names:
            instances_preview.append({
                "name": name,
                "type": inst.get("instance_type", "sonarr"),
                "status": "conflict_skip",
                "needs_api_key": False,
            })
        else:
            instances_preview.append({
                "name": name,
                "type": inst.get("instance_type", "sonarr"),
                "status": "new",
                "needs_api_key": True,
            })
            new_instance_names.add(name)

    # Analyze queues
    queues_preview = []
    for q in data.get("search_queues", []):
        inst_name = export_id_to_name.get(q.get("instance_id"))
        if inst_name and inst_name not in new_instance_names and inst_name not in existing_instance_names:
            status = "skip_no_instance"
        elif inst_name and inst_name in existing_instance_names and inst_name not in new_instance_names:
            status = "skip_instance_conflict"
        else:
            status = "new"
        queues_preview.append({
            "name": q.get("name", ""),
            "instance_name": inst_name or "Unknown",
            "status": status,
        })

    # Analyze exclusions
    exclusions_count = len(data.get("exclusions", []))

    # Analyze notifications
    notif = data.get("notifications")
    notif_preview = {"has_config": False, "needs_webhook": False}
    if notif and isinstance(notif, dict):
        if existing_has_notifications:
            notif_preview = {"has_config": True, "needs_webhook": False, "status": "conflict_skip"}
        else:
            notif_preview = {"has_config": True, "needs_webhook": True}

    return {
        "valid": True,
        "version": data.get("splintarr_version", "unknown"),
        "instances": instances_preview,
        "queues": queues_preview,
        "exclusions_count": exclusions_count,
        "notifications": notif_preview,
        "errors": errors,
    }
```

**Step 4: Run tests — should pass**

**Step 5: Commit**

```bash
git add src/splintarr/services/config_import.py tests/unit/test_config_import.py
git commit -m "feat: add config import validation service with preview

validate_import_data checks structure, detects conflicts, marks
instances needing API keys. 5 unit tests.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Import Service — Apply Import

**Files:**
- Modify: `src/splintarr/services/config_import.py` (add `apply_import`)
- Create: `tests/unit/test_config_import_apply.py`

**Step 1: Write the failing test**

```python
"""Tests for config import apply logic."""
import pytest
from unittest.mock import MagicMock, patch

from splintarr.services.config_import import apply_import


class TestApplyImport:
    def test_creates_instance_with_encrypted_key(self):
        db = MagicMock()
        data = {
            "instances": [
                {"name": "New Sonarr", "instance_type": "sonarr", "url": "http://sonarr:8989",
                 "api_key": "[REDACTED]", "is_active": True, "verify_ssl": True,
                 "timeout_seconds": 30, "rate_limit_per_second": 5.0}
            ],
            "search_queues": [],
            "exclusions": [],
            "notifications": None,
        }
        secrets = {"instances": {"New Sonarr": "real-api-key-here"}, "webhook_url": None}

        with patch("splintarr.services.config_import.encrypt_field", return_value="encrypted"):
            result = apply_import(data, secrets, user_id=1, db=db)

        assert result["imported"]["instances"] == 1
        assert db.add.called

    def test_skips_existing_instance(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = MagicMock()  # exists
        data = {
            "instances": [
                {"name": "Existing", "instance_type": "sonarr", "url": "http://sonarr:8989",
                 "api_key": "[REDACTED]", "is_active": True, "verify_ssl": True,
                 "timeout_seconds": 30, "rate_limit_per_second": 5.0}
            ],
            "search_queues": [],
            "exclusions": [],
            "notifications": None,
        }
        secrets = {"instances": {}, "webhook_url": None}

        result = apply_import(data, secrets, user_id=1, db=db)
        assert result["skipped"]["instances"] == 1

    def test_rollback_on_error(self):
        db = MagicMock()
        db.add.side_effect = Exception("DB error")
        data = {
            "instances": [
                {"name": "Fail", "instance_type": "sonarr", "url": "http://sonarr:8989",
                 "api_key": "[REDACTED]", "is_active": True, "verify_ssl": True,
                 "timeout_seconds": 30, "rate_limit_per_second": 5.0}
            ],
            "search_queues": [],
            "exclusions": [],
            "notifications": None,
        }
        secrets = {"instances": {"Fail": "key"}, "webhook_url": None}

        with patch("splintarr.services.config_import.encrypt_field", return_value="enc"):
            with pytest.raises(Exception):
                apply_import(data, secrets, user_id=1, db=db)

        db.rollback.assert_called()
```

**Step 2: Implement `apply_import`**

Add to `config_import.py`:

```python
from splintarr.core.security import encrypt_field
from splintarr.models.exclusion import SearchExclusion
from splintarr.models.instance import Instance
from splintarr.models.notification import NotificationConfig
from splintarr.models.search_queue import SearchQueue


def apply_import(
    data: dict[str, Any],
    secrets: dict[str, Any],
    user_id: int,
    db: Any,
) -> dict[str, Any]:
    """Apply an imported configuration atomically.

    Args:
        data: The original export JSON
        secrets: User-provided secrets (instance API keys + webhook URL)
        user_id: Current user's ID
        db: Database session

    Returns:
        dict with imported/skipped counts

    Raises:
        Exception: On any error (after rollback)
    """
    imported = {"instances": 0, "queues": 0, "exclusions": 0, "notifications": False}
    skipped = {"instances": 0, "queues": 0, "exclusions": 0}

    try:
        # Build export_id -> name mapping
        export_id_to_name: dict[int, str] = {}
        for inst in data.get("instances", []):
            if "id" in inst:
                export_id_to_name[inst["id"]] = inst.get("name", "")

        # Import instances — build name -> new_id mapping
        name_to_id: dict[str, int] = {}
        instance_api_keys = secrets.get("instances", {})

        for inst_data in data.get("instances", []):
            name = inst_data.get("name", "")

            # Check if exists
            existing = (
                db.query(Instance)
                .filter(Instance.user_id == user_id, Instance.name == name)
                .first()
            )
            if existing:
                name_to_id[name] = existing.id
                skipped["instances"] += 1
                continue

            api_key = instance_api_keys.get(name)
            if not api_key:
                skipped["instances"] += 1
                continue

            instance = Instance(
                user_id=user_id,
                name=name,
                instance_type=inst_data.get("instance_type", "sonarr"),
                url=inst_data.get("url", ""),
                api_key=encrypt_field(api_key),
                is_active=inst_data.get("is_active", True),
                verify_ssl=inst_data.get("verify_ssl", True),
                timeout_seconds=inst_data.get("timeout_seconds", 30),
                rate_limit_per_second=inst_data.get("rate_limit_per_second", 5.0),
            )
            db.add(instance)
            db.flush()  # Get the ID without committing
            name_to_id[name] = instance.id
            imported["instances"] += 1

        # Import queues
        for q_data in data.get("search_queues", []):
            inst_name = export_id_to_name.get(q_data.get("instance_id"))
            if not inst_name or inst_name not in name_to_id:
                skipped["queues"] += 1
                continue

            queue = SearchQueue(
                instance_id=name_to_id[inst_name],
                name=q_data.get("name", "Imported Queue"),
                strategy=q_data.get("strategy", "missing"),
                is_recurring=q_data.get("is_recurring", False),
                interval_hours=q_data.get("interval_hours"),
                is_active=q_data.get("is_active", True),
                filters=q_data.get("filters"),
            )
            db.add(queue)
            imported["queues"] += 1

        # Import exclusions
        for exc_data in data.get("exclusions", []):
            inst_name = export_id_to_name.get(exc_data.get("instance_id"))
            if not inst_name or inst_name not in name_to_id:
                skipped["exclusions"] += 1
                continue

            exclusion = SearchExclusion(
                user_id=user_id,
                instance_id=name_to_id[inst_name],
                external_id=exc_data.get("external_id"),
                content_type=exc_data.get("content_type", "series"),
                title=exc_data.get("title", ""),
                reason=exc_data.get("reason", "Imported"),
                expires_at=None,  # Don't import expiration dates
            )
            db.add(exclusion)
            imported["exclusions"] += 1

        # Import notifications
        webhook_url = secrets.get("webhook_url")
        notif_data = data.get("notifications")
        if notif_data and webhook_url:
            existing_notif = (
                db.query(NotificationConfig)
                .filter(NotificationConfig.user_id == user_id)
                .first()
            )
            if not existing_notif:
                notif = NotificationConfig(
                    user_id=user_id,
                    webhook_url=encrypt_field(webhook_url),
                    is_active=notif_data.get("is_active", True),
                )
                notif.set_events(notif_data.get("events_enabled", {}))
                db.add(notif)
                imported["notifications"] = True

        db.commit()

        logger.info(
            "config_import_completed",
            user_id=user_id,
            imported_instances=imported["instances"],
            imported_queues=imported["queues"],
            imported_exclusions=imported["exclusions"],
        )

        return {"imported": imported, "skipped": skipped}

    except Exception as e:
        db.rollback()
        logger.error("config_import_failed", user_id=user_id, error=str(e))
        raise
```

**Step 3: Run tests**

**Step 4: Commit**

```bash
git add src/splintarr/services/config_import.py tests/unit/test_config_import_apply.py
git commit -m "feat: add apply_import with atomic import and rollback

Creates instances (encrypted API keys), queues, exclusions,
notifications. Skips conflicts. 3 unit tests.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: API Endpoints — Preview + Apply

**Files:**
- Modify: `src/splintarr/api/config.py` (add two endpoints)

**Step 1: Add preview endpoint**

```python
@router.post("/import/preview", include_in_schema=False)
@limiter.limit("10/minute")
async def import_preview(
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Validate import file and return preview of what will be imported."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"valid": False, "errors": ["Invalid JSON"]},
        )

    existing_names = {
        inst.name
        for inst in db.query(Instance).filter(Instance.user_id == current_user.id).all()
    }
    existing_notif = (
        db.query(NotificationConfig)
        .filter(NotificationConfig.user_id == current_user.id)
        .first()
    )

    from splintarr.services.config_import import validate_import_data

    result = validate_import_data(
        body,
        existing_instance_names=existing_names,
        existing_has_notifications=existing_notif is not None,
    )

    logger.info(
        "config_import_preview_generated",
        user_id=current_user.id,
        valid=result["valid"],
    )

    return JSONResponse(content=result)
```

**Step 2: Add apply endpoint**

```python
@router.post("/import/apply", include_in_schema=False)
@limiter.limit("5/minute")
async def import_apply(
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Apply an imported configuration with user-provided secrets."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON"})

    config_data = body.get("config")
    secrets = body.get("secrets", {})

    if not config_data:
        return JSONResponse(status_code=400, content={"error": "Missing config data"})

    from splintarr.services.config_import import apply_import

    try:
        result = apply_import(
            data=config_data,
            secrets=secrets,
            user_id=current_user.id,
            db=db,
        )
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(
            "config_import_apply_failed",
            user_id=current_user.id,
            error=str(e),
        )
        return JSONResponse(
            status_code=500,
            content={"error": "Import failed. All changes have been rolled back."},
        )
```

**Step 3: Lint and commit**

```bash
git add src/splintarr/api/config.py
git commit -m "feat: add config import preview and apply API endpoints

POST /api/config/import/preview — validates and returns conflict preview
POST /api/config/import/apply — atomic import with user-provided secrets

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Settings UI — File Upload + Preview Modal

**Files:**
- Modify: `src/splintarr/templates/dashboard/settings.html`

**Step 1: Replace the "Config import will be available in a future release" text with a file upload**

Find line 266 (`<small style="display: block; ...">Config import will be available in a future release.</small>`) and replace with:

```html
<hr>

<h4>Config Import</h4>
<p>Upload a previously exported configuration file to restore your setup. You'll need to re-enter API keys and webhook URLs.</p>
<input type="file" id="importConfigFile" accept=".json" style="margin-bottom: 0.5rem;">
<button id="importConfigBtn" class="secondary" disabled>Upload & Preview</button>
<small id="importConfigStatus" style="display: block; margin-top: 0.5rem;"></small>

<!-- Import Preview Modal -->
<dialog id="importPreviewModal">
    <article style="max-width: 600px; margin: auto;">
        <header>
            <button aria-label="Close" rel="prev" onclick="document.getElementById('importPreviewModal').close()"></button>
            <h3>Import Preview</h3>
        </header>
        <div id="importPreviewContent"></div>
        <footer>
            <button class="secondary" onclick="document.getElementById('importPreviewModal').close()">Cancel</button>
            <button id="importApplyBtn">Import</button>
        </footer>
    </article>
</dialog>
```

**Step 2: Add JavaScript for file upload, preview, and apply**

The JS should:
1. Enable the upload button when a file is selected
2. On click, read the file, POST to `/api/config/import/preview`
3. Build the preview modal content (instances with API key inputs, queues, notification webhook input)
4. On "Import" button click, collect secrets from inputs and POST to `/api/config/import/apply`
5. Show success/error toast

```javascript
// Config Import
document.getElementById('importConfigFile').addEventListener('change', function() {
    document.getElementById('importConfigBtn').disabled = !this.files.length;
});

document.getElementById('importConfigBtn').addEventListener('click', async function() {
    var fileInput = document.getElementById('importConfigFile');
    if (!fileInput.files.length) return;

    var btn = this;
    btn.setAttribute('aria-busy', 'true');
    btn.disabled = true;

    try {
        var text = await fileInput.files[0].text();
        var configData = JSON.parse(text);

        var response = await fetch('/api/config/import/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: text,
        });
        var preview = await response.json();

        if (!preview.valid) {
            document.getElementById('importConfigStatus').textContent = 'Invalid file: ' + (preview.errors || []).join(', ');
            return;
        }

        // Store config data for apply step
        window._importConfigData = configData;

        // Build preview modal content
        var content = document.getElementById('importPreviewContent');
        content.textContent = '';

        // Instances
        if (preview.instances.length > 0) {
            var h = document.createElement('h5');
            h.textContent = 'Instances';
            content.appendChild(h);

            preview.instances.forEach(function(inst) {
                var div = document.createElement('div');
                div.style.cssText = 'margin-bottom: 0.75rem; padding: 0.5rem; border: 1px solid var(--muted-border-color); border-radius: 4px;';

                var label = document.createElement('div');
                label.style.cssText = 'display: flex; justify-content: space-between; align-items: center;';
                var nameSpan = document.createElement('strong');
                nameSpan.textContent = inst.name;
                label.appendChild(nameSpan);

                var badge = document.createElement('small');
                if (inst.status === 'new') {
                    badge.textContent = 'New';
                    badge.style.color = 'var(--ins-color)';
                } else {
                    badge.textContent = 'Skip (exists)';
                    badge.style.color = 'var(--muted-color)';
                }
                label.appendChild(badge);
                div.appendChild(label);

                if (inst.needs_api_key) {
                    var input = document.createElement('input');
                    input.type = 'password';
                    input.placeholder = 'API Key for ' + inst.name;
                    input.dataset.instanceName = inst.name;
                    input.classList.add('import-api-key');
                    input.style.marginTop = '0.5rem';
                    div.appendChild(input);
                }

                content.appendChild(div);
            });
        }

        // Queues summary
        var newQueues = preview.queues.filter(function(q) { return q.status === 'new'; });
        if (newQueues.length > 0) {
            var qh = document.createElement('h5');
            qh.textContent = 'Search Queues (' + newQueues.length + ' new)';
            content.appendChild(qh);
            newQueues.forEach(function(q) {
                var p = document.createElement('div');
                p.style.cssText = 'font-size: 0.85rem; margin-bottom: 0.25rem;';
                p.textContent = q.name + ' → ' + q.instance_name;
                content.appendChild(p);
            });
        }

        // Exclusions
        if (preview.exclusions_count > 0) {
            var eh = document.createElement('h5');
            eh.textContent = 'Exclusions (' + preview.exclusions_count + ')';
            content.appendChild(eh);
        }

        // Notifications
        if (preview.notifications && preview.notifications.has_config && preview.notifications.needs_webhook) {
            var nh = document.createElement('h5');
            nh.textContent = 'Notifications';
            content.appendChild(nh);
            var webhookInput = document.createElement('input');
            webhookInput.type = 'password';
            webhookInput.id = 'importWebhookUrl';
            webhookInput.placeholder = 'Discord Webhook URL';
            content.appendChild(webhookInput);
        }

        document.getElementById('importPreviewModal').showModal();

    } catch (err) {
        document.getElementById('importConfigStatus').textContent = 'Error: ' + err.message;
    } finally {
        btn.removeAttribute('aria-busy');
        btn.disabled = false;
    }
});

// Apply import
document.getElementById('importApplyBtn').addEventListener('click', async function() {
    var btn = this;
    btn.setAttribute('aria-busy', 'true');

    // Collect secrets
    var instanceSecrets = {};
    document.querySelectorAll('.import-api-key').forEach(function(input) {
        if (input.value) instanceSecrets[input.dataset.instanceName] = input.value;
    });
    var webhookInput = document.getElementById('importWebhookUrl');
    var webhookUrl = webhookInput ? webhookInput.value : null;

    try {
        var response = await fetch('/api/config/import/apply', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                config: window._importConfigData,
                secrets: { instances: instanceSecrets, webhook_url: webhookUrl },
            }),
        });
        var result = await response.json();

        if (response.ok) {
            document.getElementById('importPreviewModal').close();
            var msg = 'Import complete: ' + result.imported.instances + ' instances, ' +
                      result.imported.queues + ' queues, ' + result.imported.exclusions + ' exclusions.';
            Splintarr.showNotification(msg);
            setTimeout(function() { window.location.reload(); }, 1500);
        } else {
            Splintarr.showNotification(result.error || 'Import failed');
        }
    } catch (err) {
        Splintarr.showNotification('Import failed: ' + err.message);
    } finally {
        btn.removeAttribute('aria-busy');
    }
});
```

**Step 3: Commit**

```bash
git add src/splintarr/templates/dashboard/settings.html
git commit -m "feat: add config import UI with file upload and preview modal

File upload, preview with API key inputs, one-click import.
Replaces 'coming in a future release' placeholder.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Update Config Export Version

**Files:**
- Modify: `src/splintarr/api/config.py:123` (update hardcoded version)

**Step 1: Replace hardcoded version with dynamic version**

Change line 123 from:
```python
        "splintarr_version": "0.2.1",
```
To:
```python
        "splintarr_version": __version__,
```

Add the import at the top:
```python
from splintarr import __version__
```

**Step 2: Commit**

```bash
git add src/splintarr/api/config.py
git commit -m "fix: use dynamic version in config export instead of hardcoded 0.2.1

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Lint + Final Verification

**Step 1: Lint all modified files**

```bash
.venv/bin/ruff check src/splintarr/services/config_import.py src/splintarr/api/config.py
```

**Step 2: Run all import tests**

```bash
.venv/bin/python -m pytest tests/unit/test_config_import.py tests/unit/test_config_import_apply.py -v --no-cov
```

**Step 3: Run full unit test suite**

```bash
.venv/bin/python -m pytest tests/unit/ --no-cov -q
```

**Step 4: Commit any fixes**
