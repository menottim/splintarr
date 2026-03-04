"""
Update checker API endpoints.

Provides endpoints for checking update status, dismissing update notifications,
and toggling update checking.
"""

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from splintarr import __version__
from splintarr.core.auth import get_current_user_from_cookie
from splintarr.database import get_db
from splintarr.models.user import User
from splintarr.services.update_checker import (
    check_for_updates,
    get_update_state,
    is_update_available,
)

logger = structlog.get_logger()
limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/api/updates", tags=["updates"])


@router.get("/status")
@limiter.limit("10/minute")
async def update_status(
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie),
) -> JSONResponse:
    """Return current update check state."""
    state = get_update_state()
    latest = state.get("latest_version")
    logger.debug(
        "update_status_requested",
        user_id=current_user.id,
        latest_version=latest,
    )
    return JSONResponse(content={
        **state,
        "current_version": __version__,
        "update_available": is_update_available(__version__, latest) if latest else False,
    })


@router.post("/check")
@limiter.limit("5/minute")
async def check_now(
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie),
) -> JSONResponse:
    """Trigger a fresh update check against GitHub."""
    logger.info("update_check_manual_triggered", user_id=current_user.id)
    state = await check_for_updates()
    latest = state.get("latest_version")
    return JSONResponse(content={
        **state,
        "current_version": __version__,
        "update_available": is_update_available(__version__, latest) if latest else False,
    })


@router.post("/dismiss")
@limiter.limit("10/minute")
async def dismiss_update(
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Dismiss update notification for the current latest version."""
    state = get_update_state()
    latest = state.get("latest_version")
    if latest:
        current_user.dismissed_update_version = latest
        db.commit()
        logger.debug("update_notification_dismissed", user_id=current_user.id, version=latest)
    return JSONResponse(content={"dismissed": latest})


@router.post("/toggle")
@limiter.limit("10/minute")
async def toggle_update_check(
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Set automatic update checking on/off."""
    try:
        body = await request.json()
        enabled = bool(body.get("enabled"))
    except Exception:
        # Fallback to toggle if no body provided
        enabled = not current_user.update_check_enabled
    current_user.update_check_enabled = enabled
    db.commit()
    logger.info(
        "update_check_toggled",
        user_id=current_user.id,
        enabled=current_user.update_check_enabled,
    )
    return JSONResponse(content={"enabled": current_user.update_check_enabled})
