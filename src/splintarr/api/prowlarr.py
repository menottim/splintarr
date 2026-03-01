"""
Prowlarr Integration API endpoints for Splintarr.

This module provides REST API endpoints for managing Prowlarr connection
configuration:
- Get current Prowlarr config (API key masked)
- Save/update Prowlarr config (encrypts API key)
- Test Prowlarr connection
- Delete Prowlarr config

All endpoints require cookie-based authentication and rate limiting.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from splintarr.config import settings
from splintarr.core.auth import get_current_user_from_cookie
from splintarr.core.rate_limit import rate_limit_key_func
from splintarr.core.security import decrypt_field, encrypt_field
from splintarr.core.ssrf_protection import SSRFError, validate_instance_url
from splintarr.database import get_db
from splintarr.models.prowlarr import ProwlarrConfig
from splintarr.models.user import User
from splintarr.services.prowlarr import ProwlarrClient

logger = structlog.get_logger()

# Create router
router = APIRouter(
    prefix="/api/prowlarr",
    tags=["prowlarr"],
)

# Rate limiter
limiter = Limiter(key_func=rate_limit_key_func)


# ---------------------------------------------------------------------------
# Request / response schemas (inline — small enough not to need a file)
# ---------------------------------------------------------------------------


class ProwlarrConfigRequest(BaseModel):
    """Request body for saving Prowlarr config."""

    url: str
    api_key: str
    verify_ssl: bool = True
    sync_interval_minutes: int = Field(default=60, ge=5, le=1440)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate Prowlarr URL with SSRF protection."""
        v = v.strip().rstrip("/")
        if not v:
            raise ValueError("Prowlarr URL cannot be empty")
        try:
            validate_instance_url(v, allow_local=settings.allow_local_instances)
        except SSRFError as e:
            raise ValueError(str(e)) from e
        return v

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        """Validate API key has minimum length."""
        v = v.strip()
        if len(v) < 20:
            raise ValueError("API key must be at least 20 characters")
        return v


class ProwlarrConfigResponse(BaseModel):
    """Response for Prowlarr config (API key masked)."""

    id: int
    url: str
    api_key_masked: str
    verify_ssl: bool
    sync_interval_minutes: int
    is_active: bool
    last_sync_at: str | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mask_api_key(encrypted_api_key: str) -> str:
    """Mask an encrypted API key, showing only last 4 chars of decrypted value."""
    try:
        decrypted = decrypt_field(encrypted_api_key)
        if len(decrypted) > 4:
            return "••••" + decrypted[-4:]
        return "••••"
    except Exception as e:
        logger.warning("prowlarr_api_key_mask_failed", error=str(e))
        return "••••key"


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


@router.get("/config", include_in_schema=False)
@limiter.limit("10/minute")
async def get_prowlarr_config(
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Get the current Prowlarr config for the authenticated user.

    Returns masked API key and connection settings.
    Returns 404 if no config exists yet.
    """
    config = db.query(ProwlarrConfig).filter(ProwlarrConfig.user_id == current_user.id).first()

    if not config:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": "No Prowlarr config found"},
        )

    logger.debug(
        "prowlarr_config_retrieved",
        user_id=current_user.id,
    )

    return JSONResponse(
        content={
            "id": config.id,
            "url": config.url,
            "api_key_masked": _mask_api_key(config.encrypted_api_key),
            "verify_ssl": config.verify_ssl,
            "sync_interval_minutes": config.sync_interval_minutes,
            "is_active": config.is_active,
            "last_sync_at": config.last_sync_at.isoformat() if config.last_sync_at else None,
        }
    )


@router.post("/config", include_in_schema=False)
@limiter.limit("10/minute")
async def save_prowlarr_config(
    request: Request,
    payload: ProwlarrConfigRequest,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Save or update Prowlarr config for the authenticated user.

    Encrypts the API key before storing. Uses upsert pattern
    (one config per user).
    """
    config = db.query(ProwlarrConfig).filter(ProwlarrConfig.user_id == current_user.id).first()

    encrypted_key = encrypt_field(payload.api_key)

    if config:
        config.url = payload.url
        config.encrypted_api_key = encrypted_key
        config.verify_ssl = payload.verify_ssl
        config.sync_interval_minutes = payload.sync_interval_minutes
        config.is_active = True
        logger.info(
            "prowlarr_config_updated",
            user_id=current_user.id,
        )
    else:
        config = ProwlarrConfig(
            user_id=current_user.id,
            url=payload.url,
            encrypted_api_key=encrypted_key,
            verify_ssl=payload.verify_ssl,
            sync_interval_minutes=payload.sync_interval_minutes,
            is_active=True,
        )
        db.add(config)
        logger.info(
            "prowlarr_config_created",
            user_id=current_user.id,
        )

    try:
        db.commit()
        db.refresh(config)
    except IntegrityError as e:
        db.rollback()
        logger.error(
            "prowlarr_config_save_failed",
            user_id=current_user.id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save Prowlarr configuration.",
        ) from e

    return JSONResponse(
        content={
            "status": "saved",
            "id": config.id,
            "url": config.url,
            "api_key_masked": _mask_api_key(config.encrypted_api_key),
            "verify_ssl": config.verify_ssl,
            "sync_interval_minutes": config.sync_interval_minutes,
            "is_active": config.is_active,
            "last_sync_at": config.last_sync_at.isoformat() if config.last_sync_at else None,
        }
    )


@router.post("/test", include_in_schema=False)
@limiter.limit("10/minute")
async def test_prowlarr_connection(
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Test connection to the user's configured Prowlarr instance.

    Uses ProwlarrClient.test_connection() to verify connectivity.
    Returns success/failure based on Prowlarr's response.
    """
    logger.debug("prowlarr_connection_test_requested", user_id=current_user.id)

    config = db.query(ProwlarrConfig).filter(ProwlarrConfig.user_id == current_user.id).first()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No Prowlarr config found. Save a configuration first.",
        )

    try:
        api_key = decrypt_field(config.encrypted_api_key)
    except Exception as e:
        logger.error(
            "prowlarr_api_key_decrypt_failed",
            user_id=current_user.id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt Prowlarr API key.",
        ) from e

    client = ProwlarrClient(
        url=config.url,
        api_key=api_key,
        verify_ssl=config.verify_ssl,
    )

    try:
        result = await client.test_connection()
    finally:
        await client.close()

    logger.info(
        "prowlarr_connection_test_completed",
        user_id=current_user.id,
        success=result["success"],
    )

    if result["success"]:
        return JSONResponse(
            content={
                "status": "success",
                "message": f"Connected to Prowlarr v{result['version']}",
                "version": result["version"],
                "response_time_ms": result["response_time_ms"],
            }
        )

    logger.warning(
        "prowlarr_connection_test_failed_response",
        user_id=current_user.id,
        error=result.get("error"),
    )

    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={
            "status": "failed",
            "message": "Failed to connect to Prowlarr.",
            "error": "Connection failed. Check URL and API key.",
        },
    )


@router.delete("/config", include_in_schema=False)
@limiter.limit("10/minute")
async def delete_prowlarr_config(
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Delete Prowlarr config for the authenticated user.

    Removes the Prowlarr connection entirely.
    """
    logger.debug("prowlarr_config_delete_requested", user_id=current_user.id)

    config = db.query(ProwlarrConfig).filter(ProwlarrConfig.user_id == current_user.id).first()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No Prowlarr config found.",
        )

    db.delete(config)
    db.commit()

    logger.info(
        "prowlarr_config_deleted",
        user_id=current_user.id,
    )

    return JSONResponse(content={"status": "deleted", "message": "Prowlarr configuration removed."})
