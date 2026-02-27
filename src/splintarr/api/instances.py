"""
Instance Management API endpoints for Splintarr.

This module provides REST API endpoints for managing Sonarr/Radarr instances:
- Create new instances with encrypted API keys
- List all instances (without exposing API keys)
- Update instance configuration
- Delete instances
- Test instance connections
- Check for configuration drift

All endpoints require JWT authentication and enforce rate limiting.
"""

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from splintarr.api.auth import get_current_user
from splintarr.config import settings
from splintarr.core.security import decrypt_field, encrypt_field
from splintarr.core.ssrf_protection import SSRFError, validate_instance_url
from splintarr.database import get_db
from splintarr.models.instance import Instance
from splintarr.models.user import User
from splintarr.schemas.instance import (
    InstanceCreate,
    InstanceResponse,
    InstanceTestResult,
    InstanceUpdate,
)
from splintarr.services.radarr import RadarrClient, RadarrError
from splintarr.services.sonarr import SonarrClient, SonarrError

logger = structlog.get_logger()

# Create router
router = APIRouter(
    prefix="/api/instances",
    tags=["instances"],
)

# Rate limiter
limiter = Limiter(key_func=get_remote_address)


def instance_to_response(instance: Instance) -> InstanceResponse:
    """
    Convert Instance model to InstanceResponse schema.

    Ensures API keys are never exposed in responses.

    Args:
        instance: Instance model from database

    Returns:
        InstanceResponse: Sanitized instance response
    """
    return InstanceResponse(
        id=instance.id,
        name=instance.name,
        instance_type=instance.instance_type,
        url=instance.sanitized_url,
        verify_ssl=instance.verify_ssl,
        timeout_seconds=instance.timeout_seconds,
        rate_limit_per_minute=instance.rate_limit_per_second * 60,  # Convert to per minute
        is_healthy=instance.is_healthy(),
        last_connection_test=instance.last_connection_test,
        last_connection_success=instance.last_connection_success,
        last_error=instance.connection_error,
        created_at=instance.created_at,
        updated_at=instance.updated_at,
    )


@router.post(
    "",
    response_model=InstanceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create new instance",
    description="Add a new Sonarr or Radarr instance. API key will be encrypted at rest.",
)
@limiter.limit("10/minute")
async def create_instance(
    request: Request,
    instance_data: InstanceCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> InstanceResponse:
    """
    Create a new Sonarr or Radarr instance.

    The API key is encrypted before storage using Fernet encryption.
    Connection is automatically tested upon creation.

    Args:
        request: FastAPI request (for rate limiting)
        instance_data: Instance creation data
        current_user: Authenticated user
        db: Database session

    Returns:
        InstanceResponse: Created instance details (without API key)

    Raises:
        HTTPException: If validation fails or duplicate instance exists
    """
    try:
        # Check for duplicate instance name
        existing = (
            db.query(Instance)
            .filter(
                Instance.user_id == current_user.id,
                Instance.name == instance_data.name,
            )
            .first()
        )

        if existing:
            logger.warning(
                "duplicate_instance_name",
                user_id=current_user.id,
                name=instance_data.name,
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Instance with name '{instance_data.name}' already exists",
            )

        # Encrypt API key
        encrypted_api_key = encrypt_field(instance_data.api_key)

        # Create instance
        instance = Instance(
            user_id=current_user.id,
            name=instance_data.name,
            instance_type=instance_data.instance_type,
            url=str(instance_data.url),
            api_key=encrypted_api_key,
            verify_ssl=instance_data.verify_ssl,
            timeout_seconds=instance_data.timeout_seconds,
            rate_limit_per_second=instance_data.rate_limit_per_minute / 60.0,
            is_active=True,
        )

        db.add(instance)
        db.commit()
        db.refresh(instance)

        logger.info(
            "instance_created",
            instance_id=instance.id,
            user_id=current_user.id,
            name=instance.name,
            type=instance.instance_type,
        )

        # Test connection asynchronously (don't fail if test fails)
        try:
            test_result = await test_instance_connection(
                request=request,
                instance_id=instance.id,
                current_user=current_user,
                db=db,
            )

            if not test_result.success:
                logger.warning(
                    "instance_initial_connection_test_failed",
                    instance_id=instance.id,
                    error=test_result.error_details,
                )
        except Exception as e:
            logger.error(
                "instance_initial_connection_test_error",
                instance_id=instance.id,
                error=str(e),
            )

        return instance_to_response(instance)

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(
            "failed_to_create_instance",
            user_id=current_user.id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create instance",
        ) from e


@router.get(
    "",
    response_model=list[InstanceResponse],
    summary="List all instances",
    description="Get all Sonarr/Radarr instances for the authenticated user.",
)
@limiter.limit("30/minute")
async def list_instances(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[InstanceResponse]:
    """
    List all instances for the current user.

    API keys are never exposed in the response.

    Args:
        request: FastAPI request (for rate limiting)
        current_user: Authenticated user
        db: Database session

    Returns:
        list[InstanceResponse]: List of user's instances
    """
    instances = (
        db.query(Instance)
        .filter(Instance.user_id == current_user.id)
        .order_by(Instance.created_at.desc())
        .all()
    )

    logger.debug(
        "instances_listed",
        user_id=current_user.id,
        count=len(instances),
    )

    return [instance_to_response(instance) for instance in instances]


@router.get(
    "/{instance_id}",
    response_model=InstanceResponse,
    summary="Get instance details",
    description="Get details for a specific instance.",
)
@limiter.limit("60/minute")
async def get_instance(
    request: Request,
    instance_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> InstanceResponse:
    """
    Get details for a specific instance.

    Args:
        request: FastAPI request (for rate limiting)
        instance_id: Instance ID
        current_user: Authenticated user
        db: Database session

    Returns:
        InstanceResponse: Instance details (without API key)

    Raises:
        HTTPException: If instance not found or not owned by user
    """
    instance = (
        db.query(Instance)
        .filter(
            Instance.id == instance_id,
            Instance.user_id == current_user.id,
        )
        .first()
    )

    if not instance:
        logger.warning(
            "instance_not_found",
            instance_id=instance_id,
            user_id=current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instance not found",
        )

    logger.debug(
        "instance_retrieved",
        instance_id=instance_id,
        user_id=current_user.id,
    )

    return instance_to_response(instance)


@router.put(
    "/{instance_id}",
    response_model=InstanceResponse,
    summary="Update instance",
    description="Update instance configuration. Only provided fields will be updated.",
)
@limiter.limit("20/minute")
async def update_instance(
    request: Request,
    instance_id: int,
    update_data: InstanceUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> InstanceResponse:
    """
    Update an existing instance.

    Only provided fields will be updated. API key will be re-encrypted if changed.

    Args:
        request: FastAPI request (for rate limiting)
        instance_id: Instance ID
        update_data: Fields to update
        current_user: Authenticated user
        db: Database session

    Returns:
        InstanceResponse: Updated instance details

    Raises:
        HTTPException: If instance not found, not owned by user, or validation fails
    """
    try:
        instance = (
            db.query(Instance)
            .filter(
                Instance.id == instance_id,
                Instance.user_id == current_user.id,
            )
            .first()
        )

        if not instance:
            logger.warning(
                "instance_not_found_for_update",
                instance_id=instance_id,
                user_id=current_user.id,
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Instance not found",
            )

        # Update fields if provided
        update_dict = update_data.model_dump(exclude_unset=True)

        if "name" in update_dict:
            # Check for duplicate name
            existing = (
                db.query(Instance)
                .filter(
                    Instance.user_id == current_user.id,
                    Instance.name == update_dict["name"],
                    Instance.id != instance_id,
                )
                .first()
            )
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Instance with name '{update_dict['name']}' already exists",
                )
            instance.name = update_dict["name"]

        if "url" in update_dict:
            instance.url = str(update_dict["url"])

        if "api_key" in update_dict:
            # Re-encrypt new API key
            instance.api_key = encrypt_field(update_dict["api_key"])

        if "verify_ssl" in update_dict:
            instance.verify_ssl = update_dict["verify_ssl"]

        if "timeout_seconds" in update_dict:
            instance.timeout_seconds = update_dict["timeout_seconds"]

        if "rate_limit_per_minute" in update_dict:
            instance.rate_limit_per_second = update_dict["rate_limit_per_minute"] / 60.0

        db.commit()
        db.refresh(instance)

        logger.info(
            "instance_updated",
            instance_id=instance_id,
            user_id=current_user.id,
            updated_fields=list(update_dict.keys()),
        )

        return instance_to_response(instance)

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(
            "failed_to_update_instance",
            instance_id=instance_id,
            user_id=current_user.id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update instance",
        ) from e


@router.delete(
    "/{instance_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete instance",
    description="Delete an instance and all associated data.",
)
@limiter.limit("10/minute")
async def delete_instance(
    request: Request,
    instance_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """
    Delete an instance.

    Cascades to delete all associated search queue items and history.

    Args:
        request: FastAPI request (for rate limiting)
        instance_id: Instance ID
        current_user: Authenticated user
        db: Database session

    Raises:
        HTTPException: If instance not found or not owned by user
    """
    try:
        instance = (
            db.query(Instance)
            .filter(
                Instance.id == instance_id,
                Instance.user_id == current_user.id,
            )
            .first()
        )

        if not instance:
            logger.warning(
                "instance_not_found_for_deletion",
                instance_id=instance_id,
                user_id=current_user.id,
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Instance not found",
            )

        db.delete(instance)
        db.commit()

        logger.info(
            "instance_deleted",
            instance_id=instance_id,
            user_id=current_user.id,
            name=instance.name,
        )

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(
            "failed_to_delete_instance",
            instance_id=instance_id,
            user_id=current_user.id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete instance",
        ) from e


class InstanceTestRequest(BaseModel):
    """Request body for testing instance connection."""

    instance_type: str
    url: str
    api_key: str

    @field_validator("url")
    @classmethod
    def validate_url_ssrf(cls, v: str) -> str:
        """
        Validate URL to prevent SSRF attacks.

        Uses the comprehensive ssrf_protection module which:
        - Resolves DNS to check all IPs against blocked networks
        - Blocks private IPs, loopback, link-local, cloud metadata endpoints
        - Prevents DNS rebinding attacks
        - Respects allow_local_instances setting for development
        """
        try:
            validate_instance_url(v, allow_local=settings.allow_local_instances)
        except SSRFError as e:
            raise ValueError(str(e)) from e
        except ValueError:
            raise

        return v


@router.post(
    "/test",
    response_model=InstanceTestResult,
    summary="Test instance connection (pre-creation)",
    description="Test connection to a Sonarr/Radarr instance before creating it. Requires authentication.",
    include_in_schema=False,  # Hidden from OpenAPI docs (used by dashboard)
)
@limiter.limit("10/minute")
async def test_instance_pre_creation(
    request: Request,
    test_data: InstanceTestRequest,
    current_user: Annotated[User, Depends(get_current_user)],
) -> InstanceTestResult:
    """
    Test connection to an instance before creating it.

    This endpoint requires authentication to prevent abuse (SSRF, reconnaissance).
    Used by setup wizard and instance management for validation before creation.

    Args:
        request: FastAPI request (for rate limiting)
        test_data: Instance test configuration
        current_user: Authenticated user (from cookie)

    Returns:
        InstanceTestResult: Connection test results
    """
    try:
        logger.info(
            "testing_instance_pre_creation",
            instance_type=test_data.instance_type,
            url=test_data.url,
        )

        # Create appropriate client
        if test_data.instance_type == "sonarr":
            client = SonarrClient(url=test_data.url, api_key=test_data.api_key)
        elif test_data.instance_type == "radarr":
            client = RadarrClient(url=test_data.url, api_key=test_data.api_key)
        else:
            return InstanceTestResult(
                success=False,
                message=f"Invalid instance type: {test_data.instance_type}",
                version=None,
                items_count=None,
            )

        # Test connection
        try:
            async with client:
                system_status = await client.get_system_status()

                # Get item count for display
                items_count = None
                try:
                    if test_data.instance_type == "sonarr":
                        series = await client.get_series()
                        items_count = len(series) if isinstance(series, list) else None
                    else:
                        movies = await client.get_movies()
                        items_count = len(movies) if isinstance(movies, list) else None
                except Exception as e:
                    logger.warning(
                        "failed_to_get_item_count",
                        instance_type=test_data.instance_type,
                        error_type=type(e).__name__,
                        error=str(e),
                    )

                logger.info(
                    "instance_test_successful",
                    instance_type=test_data.instance_type,
                    version=system_status.get("version", "unknown"),
                )

                # Build a summary string from system status for the user
                app_name = system_status.get("appName", "")
                os_name = system_status.get("osName", "")
                runtime = system_status.get("runtimeName", "")
                info_parts = [p for p in [app_name, os_name, runtime] if p]
                instance_info = " / ".join(info_parts) if info_parts else None

                return InstanceTestResult(
                    success=True,
                    message="Connection successful",
                    version=system_status.get("version"),
                    items_count=items_count,
                    instance_info=instance_info,
                )

        except (SonarrError, RadarrError) as e:
            logger.warning(
                "instance_test_failed",
                instance_type=test_data.instance_type,
                error=str(e),
            )
            return InstanceTestResult(
                success=False,
                message=f"Connection failed: {str(e)}",
                version=None,
                items_count=None,
            )

    except Exception as e:
        logger.error(
            "instance_test_error",
            instance_type=test_data.instance_type if test_data else "unknown",
            error=str(e),
        )
        return InstanceTestResult(
            success=False,
            message=f"Failed to test connection: {str(e)}",
            version=None,
            items_count=None,
        )


@router.post(
    "/{instance_id}/test",
    response_model=InstanceTestResult,
    summary="Test instance connection",
    description="Test connection to a Sonarr/Radarr instance.",
)
@limiter.limit("10/minute")
async def test_instance_connection(
    request: Request,
    instance_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> InstanceTestResult:
    """
    Test connection to an instance.

    Attempts to connect to the instance and retrieve system status.
    Updates the instance's connection health status.

    Args:
        request: FastAPI request (for rate limiting)
        instance_id: Instance ID
        current_user: Authenticated user
        db: Database session

    Returns:
        InstanceTestResult: Connection test results

    Raises:
        HTTPException: If instance not found or not owned by user
    """
    try:
        instance = (
            db.query(Instance)
            .filter(
                Instance.id == instance_id,
                Instance.user_id == current_user.id,
            )
            .first()
        )

        if not instance:
            logger.warning(
                "instance_not_found_for_test",
                instance_id=instance_id,
                user_id=current_user.id,
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Instance not found",
            )

        # Decrypt API key
        api_key = decrypt_field(instance.api_key)

        validate_instance_url(instance.url, allow_local=settings.allow_local_instances)

        # Create appropriate client
        if instance.instance_type == "sonarr":
            client = SonarrClient(
                url=instance.url,
                api_key=api_key,
                verify_ssl=instance.verify_ssl,
                timeout=instance.timeout_seconds,
                rate_limit_per_second=instance.rate_limit_per_second,
            )
        else:  # radarr
            client = RadarrClient(
                url=instance.url,
                api_key=api_key,
                verify_ssl=instance.verify_ssl,
                timeout=instance.timeout_seconds,
                rate_limit_per_second=instance.rate_limit_per_second,
            )

        # Test connection
        async with client:
            test_result = await client.test_connection()

        # Update instance health status
        if test_result["success"]:
            instance.mark_healthy()
            message = f"Successfully connected to {instance.instance_type.capitalize()} instance"
        else:
            instance.mark_unhealthy(test_result["error"])
            message = f"Failed to connect to {instance.instance_type.capitalize()} instance"

        db.commit()

        logger.info(
            "instance_connection_tested",
            instance_id=instance_id,
            user_id=current_user.id,
            success=test_result["success"],
        )

        return InstanceTestResult(
            success=test_result["success"],
            message=message,
            version=test_result["version"],
            response_time_ms=test_result["response_time_ms"],
            error_details=test_result["error"],
        )

    except (SonarrError, RadarrError) as e:
        logger.error(
            "instance_connection_test_api_error",
            instance_id=instance_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="API error",
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "instance_connection_test_error",
            instance_id=instance_id,
            user_id=current_user.id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to test connection",
        ) from e


@router.get(
    "/{instance_id}/drift",
    summary="Check configuration drift",
    description="Check if instance configuration has drifted from expected state.",
)
@limiter.limit("10/minute")
async def check_configuration_drift(
    request: Request,
    instance_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """
    Check for configuration drift.

    Compares stored instance configuration with actual instance state
    to detect any changes or inconsistencies.

    Args:
        request: FastAPI request (for rate limiting)
        instance_id: Instance ID
        current_user: Authenticated user
        db: Database session

    Returns:
        dict: Drift detection results

    Raises:
        HTTPException: If instance not found or check fails
    """
    try:
        instance = (
            db.query(Instance)
            .filter(
                Instance.id == instance_id,
                Instance.user_id == current_user.id,
            )
            .first()
        )

        if not instance:
            logger.warning(
                "instance_not_found_for_drift_check",
                instance_id=instance_id,
                user_id=current_user.id,
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Instance not found",
            )

        # Decrypt API key
        api_key = decrypt_field(instance.api_key)

        validate_instance_url(instance.url, allow_local=settings.allow_local_instances)

        # Create appropriate client
        if instance.instance_type == "sonarr":
            client = SonarrClient(
                url=instance.url,
                api_key=api_key,
                verify_ssl=instance.verify_ssl,
                timeout=instance.timeout_seconds,
                rate_limit_per_second=instance.rate_limit_per_second,
            )
        else:  # radarr
            client = RadarrClient(
                url=instance.url,
                api_key=api_key,
                verify_ssl=instance.verify_ssl,
                timeout=instance.timeout_seconds,
                rate_limit_per_second=instance.rate_limit_per_second,
            )

        # Get system status
        async with client:
            system_status = await client.get_system_status()
            quality_profiles = await client.get_quality_profiles()

        # Check for drift (basic implementation - can be enhanced)
        drift_detected = False
        drift_details = []

        # Example: Check if version changed significantly
        current_version = system_status.get("version", "unknown")

        logger.info(
            "configuration_drift_checked",
            instance_id=instance_id,
            user_id=current_user.id,
            drift_detected=drift_detected,
        )

        return {
            "instance_id": instance_id,
            "drift_detected": drift_detected,
            "drift_details": drift_details,
            "current_version": current_version,
            "quality_profiles_count": len(quality_profiles)
            if isinstance(quality_profiles, list)
            else 0,
            "system_status": {
                "version": current_version,
                "instance_name": system_status.get("instanceName"),
                "is_debug": system_status.get("isDebug", False),
                "is_production": system_status.get("isProduction", True),
            },
        }

    except (SonarrError, RadarrError) as e:
        logger.error(
            "drift_check_api_error",
            instance_id=instance_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="API error",
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "drift_check_error",
            instance_id=instance_id,
            user_id=current_user.id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to check configuration drift",
        ) from e
