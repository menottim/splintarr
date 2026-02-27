"""
Library API endpoints for Splintarr.

HTML page routes (cookie auth):
  GET /dashboard/library            - Poster grid overview
  GET /dashboard/library/missing    - Missing content filtered view
  GET /dashboard/library/{item_id}  - Item detail with episode breakdown

JSON API routes (cookie auth, rate-limited):
  POST /api/library/sync            - Trigger manual sync (202 Accepted)
  GET  /api/library/stats           - Aggregate statistics
  GET  /api/library/items           - Paginated, filterable item list
"""

from collections import defaultdict
from typing import Any

import structlog
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from splintarr.core.auth import get_current_user_from_cookie
from splintarr.database import get_db
from splintarr.models.instance import Instance
from splintarr.models.library import LibraryEpisode, LibraryItem
from splintarr.models.user import User
from splintarr.services.library_sync import get_sync_service

logger = structlog.get_logger()

router = APIRouter(tags=["library"])
templates = Jinja2Templates(directory="src/splintarr/templates")
limiter = Limiter(key_func=get_remote_address)


# ============================================================================
# HELPERS
# ============================================================================


async def _run_sync_all_background() -> None:
    """Background task: sync library data from all active instances."""
    try:
        service = get_sync_service()
        result = await service.sync_all_instances()
        logger.info(
            "library_sync_background_completed",
            items_synced=result.get("items_synced", 0),
            error_count=len(result.get("errors", [])),
        )
    except Exception as e:
        logger.error("library_sync_background_failed", error=str(e))


def _base_library_query(db: Session, user: User):  # type: ignore[return]
    """Query LibraryItem rows owned by user (via Instance join)."""
    return (
        db.query(LibraryItem)
        .join(Instance, LibraryItem.instance_id == Instance.id)
        .filter(Instance.user_id == user.id)
    )


def _apply_filters(
    query: Any,
    instance_id: int | None = None,
    content_type: str | None = None,
    missing_only: bool = False,
) -> Any:
    """Apply optional filters to a LibraryItem query."""
    if instance_id is not None:
        query = query.filter(LibraryItem.instance_id == instance_id)
    if content_type is not None:
        query = query.filter(LibraryItem.content_type == content_type)
    if missing_only:
        query = query.filter(
            LibraryItem.episode_have < LibraryItem.episode_count
        )
    return query


def _get_library_stats(db: Session, user: User) -> dict[str, Any]:
    """Aggregate library statistics in a single SQL query."""
    row = (
        db.query(
            func.count(LibraryItem.id).label("total"),
            func.sum(
                case(
                    (
                        LibraryItem.episode_have
                        >= LibraryItem.episode_count,
                        1,
                    ),
                    else_=0,
                )
            ).label("complete"),
            func.sum(
                case(
                    (
                        LibraryItem.episode_have
                        < LibraryItem.episode_count,
                        1,
                    ),
                    else_=0,
                )
            ).label("missing"),
            func.sum(
                case(
                    (LibraryItem.content_type == "series", 1),
                    else_=0,
                )
            ).label("series"),
            func.sum(
                case(
                    (LibraryItem.content_type == "movie", 1),
                    else_=0,
                )
            ).label("movies"),
        )
        .join(Instance, LibraryItem.instance_id == Instance.id)
        .filter(Instance.user_id == user.id)
        .one()
    )

    return {
        "total_items": row.total or 0,
        "complete_count": int(row.complete or 0),
        "missing_count": int(row.missing or 0),
        "series_count": int(row.series or 0),
        "movie_count": int(row.movies or 0),
    }


# ============================================================================
# HTML PAGE ROUTES
# ============================================================================


@router.get(
    "/dashboard/library",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def library_overview(
    request: Request,
    instance_id: int | None = Query(default=None),
    content_type: str | None = Query(default=None),
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> Response:
    """Library overview page with poster grid."""
    if content_type not in (None, "series", "movie"):
        content_type = None

    items = (
        _apply_filters(
            _base_library_query(db, current_user),
            instance_id=instance_id,
            content_type=content_type,
        )
        .order_by(LibraryItem.title)
        .all()
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

    stats = _get_library_stats(db, current_user)

    return templates.TemplateResponse(
        "dashboard/library.html",
        {
            "request": request,
            "user": current_user,
            "active_page": "library",
            "items": items,
            "instances": instances,
            "stats": stats,
            "selected_instance_id": instance_id,
            "selected_content_type": content_type,
        },
    )


@router.get(
    "/dashboard/library/missing",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def library_missing(
    request: Request,
    instance_id: int | None = Query(default=None),
    content_type: str | None = Query(default=None),
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> Response:
    """Missing content filtered view."""
    if content_type not in (None, "series", "movie"):
        content_type = None

    items = (
        _apply_filters(
            _base_library_query(db, current_user),
            instance_id=instance_id,
            content_type=content_type,
            missing_only=True,
        )
        .order_by(LibraryItem.title)
        .all()
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

    stats = _get_library_stats(db, current_user)

    return templates.TemplateResponse(
        "dashboard/library_missing.html",
        {
            "request": request,
            "user": current_user,
            "active_page": "library",
            "items": items,
            "instances": instances,
            "stats": stats,
            "selected_instance_id": instance_id,
            "selected_content_type": content_type,
        },
    )


@router.get(
    "/dashboard/library/{item_id}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def library_item_detail(
    request: Request,
    item_id: int,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> Response:
    """Item detail page with episode breakdown."""
    item = (
        _base_library_query(db, current_user)
        .filter(LibraryItem.id == item_id)
        .first()
    )

    if not item:
        return RedirectResponse(
            url="/dashboard/library",
            status_code=status.HTTP_302_FOUND,
        )

    seasons: dict[int, list[LibraryEpisode]] = defaultdict(list)
    if item.content_type == "series":
        episodes = (
            db.query(LibraryEpisode)
            .filter(LibraryEpisode.library_item_id == item.id)
            .order_by(
                LibraryEpisode.season_number,
                LibraryEpisode.episode_number,
            )
            .all()
        )
        for ep in episodes:
            seasons[ep.season_number].append(ep)

    return templates.TemplateResponse(
        "dashboard/library_detail.html",
        {
            "request": request,
            "user": current_user,
            "active_page": "library",
            "item": item,
            "seasons": dict(sorted(seasons.items())),
        },
    )


# ============================================================================
# JSON API ROUTES
# ============================================================================


@router.post("/api/library/sync", include_in_schema=False)
@limiter.limit("5/minute")
async def api_library_sync(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user_from_cookie),
) -> JSONResponse:
    """Trigger manual library sync (returns 202 Accepted)."""
    try:
        get_sync_service()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Library sync service is not available",
        ) from e

    background_tasks.add_task(_run_sync_all_background)
    logger.info("library_sync_triggered", user_id=current_user.id)

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"detail": "Library sync started"},
    )


@router.get("/api/library/stats", include_in_schema=False)
@limiter.limit("30/minute")
async def api_library_stats(
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Aggregate library statistics."""
    stats = _get_library_stats(db, current_user)
    return JSONResponse(content=stats)


@router.get("/api/library/items", include_in_schema=False)
@limiter.limit("30/minute")
async def api_library_items(
    request: Request,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=24, ge=1, le=100),
    instance_id: int | None = Query(default=None),
    content_type: str | None = Query(default=None),
    missing_only: bool = Query(default=False),
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Paginated, filterable list of library items."""
    if content_type is not None and content_type not in ("series", "movie"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="content_type must be 'series' or 'movie'",
        )

    base_q = _apply_filters(
        _base_library_query(db, current_user),
        instance_id=instance_id,
        content_type=content_type,
        missing_only=missing_only,
    )

    total = base_q.count()
    total_pages = max(1, (total + per_page - 1) // per_page)
    offset = (page - 1) * per_page

    items = (
        base_q.order_by(LibraryItem.title)
        .offset(offset)
        .limit(per_page)
        .all()
    )

    return JSONResponse(
        content={
            "items": [
                {
                    "id": item.id,
                    "instance_id": item.instance_id,
                    "content_type": item.content_type,
                    "title": item.title,
                    "year": item.year,
                    "status": item.status,
                    "episode_count": item.episode_count,
                    "episode_have": item.episode_have,
                    "missing_count": item.missing_count,
                    "completion_pct": item.completion_pct,
                    "is_complete": item.is_complete,
                    "poster_path": item.poster_path,
                }
                for item in items
            ],
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        }
    )
