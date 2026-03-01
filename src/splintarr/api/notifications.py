"""
Notification API endpoints for Splintarr.

This module provides REST API endpoints for managing Discord webhook
notification configuration:
- Get current notification config (webhook URL masked)
- Save/update notification config (encrypts webhook URL)
- Send a test notification to verify webhook connectivity

All endpoints require cookie-based authentication.
"""

import json

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from splintarr.core.auth import get_current_user_from_cookie
from splintarr.core.security import decrypt_field, encrypt_field
from splintarr.database import get_db
from splintarr.models.notification import DEFAULT_EVENTS, NotificationConfig
from splintarr.models.user import User
from splintarr.services.discord import DiscordNotificationService

logger = structlog.get_logger()

# Create router
router = APIRouter(
    prefix="/api/notifications",
    tags=["notifications"],
)


# ---------------------------------------------------------------------------
# Request / response schemas (inline — small enough not to need a file)
# ---------------------------------------------------------------------------


class NotificationConfigRequest(BaseModel):
    """Request body for saving notification config."""

    webhook_url: str
    events_enabled: dict[str, bool] | None = None
    is_active: bool = True

    @field_validator("webhook_url")
    @classmethod
    def validate_webhook_url(cls, v: str) -> str:
        """Validate that the URL looks like a Discord webhook."""
        v = v.strip()
        if not v:
            raise ValueError("Webhook URL cannot be empty")
        if not v.startswith("https://discord.com/api/webhooks/") and not v.startswith(
            "https://discordapp.com/api/webhooks/"
        ):
            raise ValueError(
                "Webhook URL must start with https://discord.com/api/webhooks/ "
                "or https://discordapp.com/api/webhooks/"
            )
        return v


class NotificationConfigResponse(BaseModel):
    """Response for notification config (webhook URL masked)."""

    id: int
    webhook_url_masked: str
    events_enabled: dict[str, bool]
    is_active: bool


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


@router.get("/config", include_in_schema=False)
async def get_notification_config(
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Get the current notification config for the authenticated user.

    Returns masked webhook URL and event settings.
    Returns 200 with configured=false if no config exists yet.
    """
    config = (
        db.query(NotificationConfig).filter(NotificationConfig.user_id == current_user.id).first()
    )

    if not config:
        return JSONResponse(content={"configured": False})

    logger.debug(
        "notification_config_retrieved",
        user_id=current_user.id,
    )

    return JSONResponse(
        content={
            "id": config.id,
            "webhook_url_masked": "••••webhook",
            "events_enabled": config.get_events(),
            "is_active": config.is_active,
        }
    )


@router.post("/config", include_in_schema=False)
async def save_notification_config(
    payload: NotificationConfigRequest,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Save or update notification config for the authenticated user.

    Encrypts the webhook URL before storing.
    """
    config = (
        db.query(NotificationConfig).filter(NotificationConfig.user_id == current_user.id).first()
    )

    encrypted_url = encrypt_field(payload.webhook_url)
    events = payload.events_enabled if payload.events_enabled else DEFAULT_EVENTS.copy()

    if config:
        config.webhook_url = encrypted_url
        config.set_events(events)
        config.is_active = payload.is_active
        logger.info(
            "notification_config_updated",
            user_id=current_user.id,
        )
    else:
        config = NotificationConfig(
            user_id=current_user.id,
            webhook_url=encrypted_url,
            events_enabled=json.dumps(events),
            is_active=payload.is_active,
        )
        db.add(config)
        logger.info(
            "notification_config_created",
            user_id=current_user.id,
        )

    db.commit()

    return JSONResponse(
        content={
            "status": "saved",
            "id": config.id,
            "webhook_url_masked": "••••webhook",
            "events_enabled": config.get_events(),
            "is_active": config.is_active,
        }
    )


@router.post("/test", include_in_schema=False)
async def test_notification(
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Send a test notification to the user's configured webhook.

    Returns success/failure based on Discord's response.
    """
    config = (
        db.query(NotificationConfig).filter(NotificationConfig.user_id == current_user.id).first()
    )

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No notification config found. Save a webhook URL first.",
        )

    try:
        webhook_url = decrypt_field(config.webhook_url)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt webhook URL.",
        ) from e

    service = DiscordNotificationService(webhook_url)
    success = await service.send_test_message()

    logger.info(
        "notification_test_sent",
        user_id=current_user.id,
        success=success,
    )

    if success:
        return JSONResponse(content={"status": "success", "message": "Test notification sent!"})

    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={"status": "failed", "message": "Discord webhook returned an error."},
    )
