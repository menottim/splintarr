"""Config Import Service for Splintarr."""
from typing import Any

import structlog

from splintarr.config import settings
from splintarr.core.security import encrypt_field
from splintarr.core.ssrf_protection import validate_instance_url
from splintarr.models.exclusion import SearchExclusion
from splintarr.models.instance import Instance
from splintarr.models.notification import NotificationConfig
from splintarr.models.search_queue import SearchQueue

logger = structlog.get_logger()

REQUIRED_KEYS = {"splintarr_version", "exported_at", "instances", "search_queues", "exclusions"}
VALID_INSTANCE_TYPES = {"sonarr", "radarr"}
VALID_STRATEGIES = {"missing", "cutoff_unmet", "recent", "custom"}
VALID_CONTENT_TYPES = {"series", "movie"}


def validate_import_data(
    data: dict[str, Any],
    existing_instance_names: set[str],
    existing_has_notifications: bool = False,
) -> dict[str, Any]:
    """Validate import data and return a preview.

    Checks structural validity of the export payload, detects conflicts with
    existing data, and builds a preview summarising what would be created,
    skipped, or require user-supplied secrets.

    Args:
        data: Parsed JSON export payload.
        existing_instance_names: Names of instances already in the database.
        existing_has_notifications: Whether the user already has notification config.

    Returns:
        dict with ``valid`` boolean, preview lists, and any errors.
    """
    errors: list[str] = []

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

    # Map export-file instance IDs to names so queues can be resolved.
    export_id_to_name: dict[int, str] = {}
    for inst in data.get("instances", []):
        if "id" in inst and "name" in inst:
            export_id_to_name[inst["id"]] = inst["name"]

    # --- Instances preview ---
    instances_preview: list[dict[str, Any]] = []
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

    # --- Queues preview ---
    queues_preview: list[dict[str, Any]] = []
    for q in data.get("search_queues", []):
        inst_name = export_id_to_name.get(q.get("instance_id"))
        if inst_name and inst_name in existing_instance_names and inst_name not in new_instance_names:
            status = "skip_instance_conflict"
        elif inst_name and (inst_name in new_instance_names or inst_name in existing_instance_names):
            status = "new"
        else:
            status = "skip_no_instance"
        queues_preview.append({
            "name": q.get("name", ""),
            "instance_name": inst_name or "Unknown",
            "status": status,
        })

    # --- Exclusions count ---
    exclusions_count = len(data.get("exclusions", []))

    # --- Notifications preview ---
    notif = data.get("notifications")
    notif_preview: dict[str, Any] = {"has_config": False, "needs_webhook": False}
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


def apply_import(
    data: dict[str, Any],
    secrets: dict[str, Any],
    user_id: int,
    db: Any,
) -> dict[str, Any]:
    """Apply an imported configuration atomically.

    Creates instances, search queues, exclusions, and notification config
    from the validated export payload.  All writes happen inside a single
    transaction -- on any failure the session is rolled back and the
    exception is re-raised.

    Args:
        data: Parsed JSON export payload (already validated).
        secrets: User-supplied secrets keyed by entity name, e.g.
            ``{"instances": {"My Sonarr": "api-key"}, "webhook_url": "https://..."}``.
        user_id: ID of the authenticated user performing the import.
        db: SQLAlchemy Session.

    Returns:
        dict with ``imported`` and ``skipped`` counts per entity type.

    Raises:
        Exception: Any DB error -- the transaction will be rolled back first.
    """
    imported: dict[str, Any] = {
        "instances": 0,
        "queues": 0,
        "exclusions": 0,
        "notifications": False,
    }
    skipped: dict[str, Any] = {"instances": 0, "queues": 0, "exclusions": 0}

    try:
        # Build export-id -> name map for resolving queue/exclusion references.
        export_id_to_name: dict[int, str] = {}
        for inst in data.get("instances", []):
            if "id" in inst:
                export_id_to_name[inst["id"]] = inst.get("name", "")

        # Pre-load all existing instance names in one query (avoids N+1)
        existing_instances = {
            row.name: row.id
            for row in db.query(Instance.name, Instance.id)
            .filter(Instance.user_id == user_id)
            .all()
        }

        # Track name -> new DB id for linking queues and exclusions.
        name_to_id: dict[str, int] = {}
        instance_api_keys = secrets.get("instances", {})

        # --- Instances ---
        for inst_data in data.get("instances", []):
            name = inst_data.get("name", "")
            if name in existing_instances:
                name_to_id[name] = existing_instances[name]
                skipped["instances"] += 1
                continue

            api_key = instance_api_keys.get(name)
            if not api_key:
                skipped["instances"] += 1
                continue

            # Validate instance_type
            inst_type = inst_data.get("instance_type", "sonarr")
            if inst_type not in VALID_INSTANCE_TYPES:
                logger.warning("config_import_invalid_instance_type", name=name, type=inst_type)
                skipped["instances"] += 1
                continue

            # SSRF check on URL
            url = inst_data.get("url", "")
            try:
                validate_instance_url(url, allow_local=settings.allow_local_instances)
            except Exception as ssrf_err:
                logger.warning("config_import_url_blocked", name=name, url=url, error=str(ssrf_err))
                skipped["instances"] += 1
                continue

            instance = Instance(
                user_id=user_id,
                name=name,
                instance_type=inst_type,
                url=url,
                api_key=encrypt_field(api_key),
                is_active=inst_data.get("is_active", True),
                verify_ssl=inst_data.get("verify_ssl", True),
                timeout_seconds=inst_data.get("timeout_seconds", 30),
                rate_limit_per_second=inst_data.get("rate_limit_per_second", 5.0),
            )
            db.add(instance)
            db.flush()
            name_to_id[name] = instance.id
            imported["instances"] += 1

        # --- Search queues ---
        for q_data in data.get("search_queues", []):
            inst_name = export_id_to_name.get(q_data.get("instance_id"))
            if not inst_name or inst_name not in name_to_id:
                skipped["queues"] += 1
                continue
            strategy = q_data.get("strategy", "missing")
            if strategy not in VALID_STRATEGIES:
                logger.warning("config_import_invalid_strategy", strategy=strategy)
                skipped["queues"] += 1
                continue
            queue = SearchQueue(
                instance_id=name_to_id[inst_name],
                name=q_data.get("name", "Imported Queue"),
                strategy=strategy,
                is_recurring=q_data.get("is_recurring", False),
                interval_hours=q_data.get("interval_hours"),
                schedule_mode=q_data.get("schedule_mode", "interval"),
                schedule_time=q_data.get("schedule_time"),
                schedule_days=q_data.get("schedule_days"),
                jitter_minutes=q_data.get("jitter_minutes", 0),
                is_active=q_data.get("is_active", True),
                filters=q_data.get("filters"),
                budget_aware=q_data.get("budget_aware", True),
            )
            db.add(queue)
            imported["queues"] += 1

        # --- Exclusions ---
        for exc_data in data.get("exclusions", []):
            inst_name = export_id_to_name.get(exc_data.get("instance_id"))
            if not inst_name or inst_name not in name_to_id:
                skipped["exclusions"] += 1
                continue
            content_type = exc_data.get("content_type", "series")
            if content_type not in VALID_CONTENT_TYPES:
                skipped["exclusions"] += 1
                continue
            exclusion = SearchExclusion(
                user_id=user_id,
                instance_id=name_to_id[inst_name],
                external_id=exc_data.get("external_id"),
                content_type=content_type,
                title=exc_data.get("title", ""),
                reason=exc_data.get("reason", "Imported"),
            )
            db.add(exclusion)
            imported["exclusions"] += 1

        # --- Notifications ---
        webhook_url = secrets.get("webhook_url")
        notif_data = data.get("notifications")
        # Validate webhook URL format (must be https Discord webhook)
        if webhook_url:
            if not webhook_url.startswith("https://"):
                logger.warning("config_import_webhook_url_invalid", user_id=user_id)
                webhook_url = None
            else:
                try:
                    validate_instance_url(webhook_url, allow_local=False)
                except Exception as e:
                    logger.warning(
                        "config_import_webhook_url_ssrf_blocked",
                        user_id=user_id,
                        error=str(e),
                    )
                    webhook_url = None
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
