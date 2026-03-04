# Config Import — Design Document

**Feature #14** | **Target Release**: v1.3.0
**Date**: 2026-03-04

## Problem

Users can export their configuration but can't restore it. No way to migrate between installations, recover from data loss, or clone a setup to a second machine.

## Flow

1. User uploads JSON file (same format as Config Export) via Settings page
2. `POST /api/config/import/preview` validates and returns a preview
3. Preview modal shows what will be imported, conflicts, and API key/webhook inputs
4. User fills in secrets and confirms
5. `POST /api/config/import/apply` atomically creates all entities
6. Redirect to Settings with success toast

## API Endpoints

### `POST /api/config/import/preview`

Accepts JSON file upload. Validates structure and version. Returns preview:

```json
{
  "valid": true,
  "version": "1.2.1",
  "instances": [
    {"name": "My Sonarr", "type": "sonarr", "status": "new", "needs_api_key": true},
    {"name": "Existing", "type": "sonarr", "status": "conflict_skip", "needs_api_key": false}
  ],
  "queues": [
    {"name": "Missing Weekly", "instance_name": "My Sonarr", "status": "new"},
    {"name": "Cutoff Daily", "instance_name": "Existing", "status": "skip_instance_conflict"}
  ],
  "exclusions_count": 5,
  "notifications": {"has_config": true, "needs_webhook": true},
  "errors": []
}
```

### `POST /api/config/import/apply`

Accepts the original config JSON + user-provided secrets:

```json
{
  "config": { ... original export JSON ... },
  "secrets": {
    "instances": {"My Sonarr": "api-key-here"},
    "webhook_url": "https://discord.com/api/webhooks/..."
  }
}
```

Returns: `{"imported": {"instances": 1, "queues": 3, "exclusions": 5, "notifications": true}, "skipped": {"instances": 1, "queues": 1}}`

## Conflict Resolution

- **Skip on conflict** — if instance name already exists, skip it
- Queues referencing a skipped instance are also skipped
- Exclusions referencing a skipped instance are also skipped
- Notification config: skip if user already has notification config

## What Gets Imported

| Entity | Imported | Secrets |
|--------|----------|---------|
| Instances | Yes | User provides API key per instance |
| Search queues | Yes (linked by instance name) | None needed |
| Exclusions | Yes (linked by instance name) | None needed |
| Notifications | Yes | User provides webhook URL |

## What Does NOT Get Imported

- Execution state (status, last_run, next_run, consecutive_failures)
- Library data (synced from instances after import)
- Search history
- Prowlarr config (separate setup)

## Instance Linking

Export uses `instance_id` but import links by **instance name**. During import:
1. Create new instances, get their IDs
2. Build a name→ID mapping (including existing instances)
3. Assign queues and exclusions to the correct instance by name lookup

## Validation

- JSON structure validation (required top-level keys)
- Version compatibility check (warn if export version > current version)
- Instance type validation (only sonarr in alpha)
- Queue strategy validation
- API key format validation (non-empty, minimum length)
- Webhook URL format validation (Discord URL pattern)

## UI

Settings page → new "Config Import" section below "Config Export":
- File upload input (accepts .json)
- Upload triggers preview modal
- Modal shows: instances (with API key inputs for new ones), queues, exclusion count, notification config (with webhook input)
- Conflicting items shown as "Skip (already exists)"
- Confirm button → apply import → success toast → page reload

## Service Layer

New `services/config_import.py`:
- `validate_import_file(data: dict) -> ImportPreview` — validates structure, checks conflicts
- `apply_import(data: dict, secrets: dict, user_id: int, db: Session) -> ImportResult` — atomic import

## Not Building
- Merge/overwrite conflict resolution
- Selective import (all or nothing per entity type)
- Import from URL
- Cross-user import
