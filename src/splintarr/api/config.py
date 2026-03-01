"""
Config API endpoints for Splintarr.

JSON API routes (cookie auth, rate-limited):
  GET  /api/config/export           - Export configuration as JSON
  POST /api/config/integrity-check  - Run database integrity check
"""

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from sqlalchemy import text
from sqlalchemy.orm import Session

from splintarr.core.auth import get_current_user_from_cookie
from splintarr.core.rate_limit import rate_limit_key_func
from splintarr.database import get_db, get_engine
from splintarr.models.exclusion import SearchExclusion
from splintarr.models.instance import Instance
from splintarr.models.notification import NotificationConfig
from splintarr.models.search_queue import SearchQueue
from splintarr.models.user import User

logger = structlog.get_logger()

router = APIRouter(prefix="/api/config", tags=["config"])
limiter = Limiter(key_func=rate_limit_key_func)


@router.get("/export", include_in_schema=False)
@limiter.limit("5/minute")
async def export_config(
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Export user configuration as a JSON download.

    Includes instances (API keys redacted), search queues, exclusions,
    and notification config (webhook URL redacted).
    """
    user_id = current_user.id

    # Query instances owned by this user
    instances = db.query(Instance).filter(Instance.user_id == user_id).order_by(Instance.id).all()
    instances_data = [
        {
            "id": inst.id,
            "name": inst.name,
            "instance_type": inst.instance_type,
            "url": inst.sanitized_url,
            "api_key": "[REDACTED]",
            "is_active": inst.is_active,
            "verify_ssl": inst.verify_ssl,
            "timeout_seconds": inst.timeout_seconds,
            "rate_limit_per_second": inst.rate_limit_per_second,
        }
        for inst in instances
    ]

    # Query search queues via instance ownership
    instance_ids = [inst.id for inst in instances]
    queues = (
        db.query(SearchQueue)
        .filter(SearchQueue.instance_id.in_(instance_ids))
        .order_by(SearchQueue.id)
        .all()
        if instance_ids
        else []
    )
    queues_data = [
        {
            "id": q.id,
            "instance_id": q.instance_id,
            "name": q.name,
            "strategy": q.strategy,
            "is_recurring": q.is_recurring,
            "interval_hours": q.interval_hours,
            "is_active": q.is_active,
            "filters": q.filters,
        }
        for q in queues
    ]

    # Query exclusions owned by this user
    exclusions = (
        db.query(SearchExclusion)
        .filter(SearchExclusion.user_id == user_id)
        .order_by(SearchExclusion.id)
        .all()
    )
    exclusions_data = [
        {
            "id": exc.id,
            "instance_id": exc.instance_id,
            "external_id": exc.external_id,
            "content_type": exc.content_type,
            "title": exc.title,
            "reason": exc.reason,
            "expires_at": exc.expires_at.isoformat() if exc.expires_at else None,
        }
        for exc in exclusions
    ]

    # Query notification config for this user
    notification = (
        db.query(NotificationConfig).filter(NotificationConfig.user_id == user_id).first()
    )
    notification_data = None
    if notification:
        notification_data = {
            "webhook_url": "[REDACTED]",
            "events_enabled": notification.get_events(),
            "is_active": notification.is_active,
        }

    export_payload = {
        "splintarr_version": "0.2.1",
        "exported_at": datetime.now(UTC).isoformat(),
        "instances": instances_data,
        "search_queues": queues_data,
        "exclusions": exclusions_data,
        "notifications": notification_data,
    }

    logger.info(
        "config_exported",
        user_id=user_id,
        instance_count=len(instances_data),
        queue_count=len(queues_data),
        exclusion_count=len(exclusions_data),
    )

    return JSONResponse(
        content=export_payload,
        headers={
            "Content-Disposition": "attachment; filename=splintarr-config.json",
        },
    )


@router.post("/integrity-check", include_in_schema=False)
@limiter.limit("5/minute")
async def integrity_check(
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie),
) -> JSONResponse:
    """
    Run a database integrity check via PRAGMA integrity_check.

    Returns status "ok" when the database is healthy, or "error" with details.
    """
    try:
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA integrity_check"))
            rows = [row[0] for row in result.fetchall()]

        if rows == ["ok"]:
            logger.info(
                "database_integrity_check_passed",
                user_id=current_user.id,
            )
            return JSONResponse(content={"status": "ok", "details": rows})

        logger.warning(
            "database_integrity_check_issues",
            user_id=current_user.id,
            details=rows,
        )
        return JSONResponse(content={"status": "error", "details": rows})

    except Exception as e:
        logger.error(
            "database_integrity_check_failed",
            user_id=current_user.id,
            error=str(e),
        )
        return JSONResponse(
            status_code=500,
            content={"status": "error", "details": ["Database integrity check could not be completed"]},
        )
