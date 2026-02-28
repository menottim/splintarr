"""
Exclusion API endpoints for Splintarr.

HTML page routes (cookie auth):
  GET /dashboard/exclusions          - Exclusion list page

JSON API routes (cookie auth, rate-limited):
  POST   /api/exclusions             - Create single exclusion
  POST   /api/exclusions/bulk        - Bulk create exclusions
  DELETE /api/exclusions/{id}        - Delete exclusion
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from slowapi import Limiter
from sqlalchemy.orm import Session

from splintarr.core.auth import get_current_user_from_cookie
from splintarr.core.rate_limit import rate_limit_key_func
from splintarr.database import get_db, get_session_factory
from splintarr.models.instance import Instance
from splintarr.models.user import User
from splintarr.services.exclusion import ExclusionService

logger = structlog.get_logger()

router = APIRouter(tags=["exclusions"])
templates = Jinja2Templates(directory="src/splintarr/templates")
limiter = Limiter(key_func=rate_limit_key_func)


# ============================================================================
# SCHEMAS
# ============================================================================


class ExclusionCreateRequest(BaseModel):
    """Request body for creating a single exclusion."""

    instance_id: int = Field(..., description="Instance ID")
    external_id: int = Field(..., description="ID in the source instance")
    content_type: str = Field(..., pattern="^(series|movie)$", description="series or movie")
    title: str = Field(..., min_length=1, max_length=500, description="Content title")
    library_item_id: int | None = Field(default=None, description="Optional LibraryItem ID")
    reason: str | None = Field(default=None, max_length=500, description="Optional reason")
    duration: str = Field(
        default="permanent",
        pattern="^(permanent|7d|30d|90d)$",
        description="Duration preset",
    )


class BulkExclusionCreateRequest(BaseModel):
    """Request body for bulk creating exclusions."""

    exclusions: list[ExclusionCreateRequest] = Field(
        ..., min_length=1, max_length=100, description="List of exclusions to create"
    )


# ============================================================================
# HTML PAGE ROUTES
# ============================================================================


@router.get(
    "/dashboard/exclusions",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def exclusions_page(
    request: Request,
    instance_id: int | None = Query(default=None),
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> Response:
    """Exclusion list page with filters."""
    exclusion_service = ExclusionService(get_session_factory())
    exclusions = exclusion_service.list_exclusions(
        user_id=current_user.id,
        instance_id=instance_id,
    )

    instances = (
        db.query(Instance)
        .filter(
            Instance.user_id == current_user.id,
            Instance.is_active == True,  # noqa: E712
        )
        .order_by(Instance.name)
        .all()
    )

    logger.debug(
        "exclusions_page_rendered",
        user_id=current_user.id,
        exclusion_count=len(exclusions),
        instance_id=instance_id,
    )

    return templates.TemplateResponse(
        "dashboard/exclusions.html",
        {
            "request": request,
            "user": current_user,
            "active_page": "exclusions",
            "exclusions": exclusions,
            "instances": instances,
            "selected_instance_id": instance_id,
        },
    )


# ============================================================================
# JSON API ROUTES
# ============================================================================


def _validate_instance_ownership(db: Session, instance_id: int, user_id: int) -> Instance:
    """Verify the user owns the given instance."""
    instance = (
        db.query(Instance)
        .filter(
            Instance.id == instance_id,
            Instance.user_id == user_id,
        )
        .first()
    )
    if not instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instance not found",
        )
    return instance


@router.post("/api/exclusions", include_in_schema=False)
@limiter.limit("30/minute")
async def api_create_exclusion(
    request: Request,
    body: ExclusionCreateRequest,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Create a single content exclusion."""
    _validate_instance_ownership(db, body.instance_id, current_user.id)

    exclusion_service = ExclusionService(get_session_factory())
    exclusion = exclusion_service.create_exclusion(
        user_id=current_user.id,
        instance_id=body.instance_id,
        external_id=body.external_id,
        content_type=body.content_type,
        title=body.title,
        library_item_id=body.library_item_id,
        reason=body.reason,
        duration=body.duration,
    )

    logger.info(
        "exclusion_api_created",
        user_id=current_user.id,
        exclusion_id=exclusion.id,
        title=body.title,
    )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "id": exclusion.id,
            "title": exclusion.title,
            "content_type": exclusion.content_type,
            "external_id": exclusion.external_id,
            "expires_at": exclusion.expires_at.isoformat() if exclusion.expires_at else None,
            "expiry_label": exclusion.expiry_label,
        },
    )


@router.post("/api/exclusions/bulk", include_in_schema=False)
@limiter.limit("10/minute")
async def api_bulk_create_exclusions(
    request: Request,
    body: BulkExclusionCreateRequest,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Bulk create content exclusions."""
    # Validate all instance IDs belong to user
    instance_ids = {exc.instance_id for exc in body.exclusions}
    for iid in instance_ids:
        _validate_instance_ownership(db, iid, current_user.id)

    exclusion_service = ExclusionService(get_session_factory())
    results = []

    for item in body.exclusions:
        exclusion = exclusion_service.create_exclusion(
            user_id=current_user.id,
            instance_id=item.instance_id,
            external_id=item.external_id,
            content_type=item.content_type,
            title=item.title,
            library_item_id=item.library_item_id,
            reason=item.reason,
            duration=item.duration,
        )
        results.append(
            {
                "id": exclusion.id,
                "title": exclusion.title,
                "content_type": exclusion.content_type,
                "external_id": exclusion.external_id,
            }
        )

    logger.info(
        "exclusion_api_bulk_created",
        user_id=current_user.id,
        count=len(results),
    )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"created": len(results), "exclusions": results},
    )


@router.delete("/api/exclusions/{exclusion_id}", include_in_schema=False)
@limiter.limit("30/minute")
async def api_delete_exclusion(
    request: Request,
    exclusion_id: int,
    current_user: User = Depends(get_current_user_from_cookie),
) -> JSONResponse:
    """Delete a content exclusion."""
    exclusion_service = ExclusionService(get_session_factory())
    deleted = exclusion_service.delete_exclusion(
        exclusion_id=exclusion_id,
        user_id=current_user.id,
    )

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Exclusion not found",
        )

    logger.info(
        "exclusion_api_deleted",
        user_id=current_user.id,
        exclusion_id=exclusion_id,
    )

    return JSONResponse(content={"detail": "Exclusion deleted"})
