"""
Dashboard API endpoints for Splintarr.

This module provides web UI endpoints for:
- Setup wizard (first-run configuration)
- Main dashboard (monitoring and statistics)
- Instance management UI
- Search queue management UI
- Search history UI
- Settings UI
- Dashboard API endpoints (JSON data for AJAX)

All dashboard pages require authentication except the setup wizard.
The setup wizard is only accessible when no users exist.
"""

import re
from datetime import datetime, timedelta
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Cookie, Depends, Form, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from splintarr.api.auth import set_auth_cookies
from splintarr.config import settings
from splintarr.core.auth import (
    TokenError,
    create_access_token,
    create_refresh_token,
    get_current_user_from_cookie,
    get_current_user_id_from_token,
)
from splintarr.core.security import encrypt_field, hash_password
from splintarr.core.ssrf_protection import SSRFError, validate_instance_url
from splintarr.database import get_db
from splintarr.models.instance import Instance
from splintarr.models.search_history import SearchHistory
from splintarr.models.search_queue import SearchQueue
from splintarr.models.user import User
from splintarr.services.radarr import RadarrClient, RadarrError
from splintarr.services.sonarr import SonarrClient, SonarrError

logger = structlog.get_logger()

# Create router
router = APIRouter(tags=["dashboard"])

# Setup Jinja2 templates
templates = Jinja2Templates(directory="src/splintarr/templates")

# Add custom filters for Jinja2
templates.env.filters["datetime"] = lambda value: (
    value.strftime("%Y-%m-%d %H:%M:%S") if value else ""
)
templates.env.filters["timeago"] = lambda value: (_timeago(value) if value else "")


def _timeago(dt: datetime) -> str:
    """Format datetime as time ago (e.g., '2 hours ago')."""
    if not dt:
        return ""

    now = datetime.utcnow()
    diff = now - dt

    if diff.total_seconds() < 60:
        return "just now"
    elif diff.total_seconds() < 3600:
        minutes = int(diff.total_seconds() / 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif diff.total_seconds() < 86400:
        hours = int(diff.total_seconds() / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif diff.total_seconds() < 604800:
        days = int(diff.total_seconds() / 86400)
        return f"{days} day{'s' if days != 1 else ''} ago"
    else:
        return dt.strftime("%Y-%m-%d")


# ============================================================================
# ROOT AND REDIRECTS
# ============================================================================


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root(
    request: Request,
    access_token: Annotated[str | None, Cookie()] = None,
    db: Session = Depends(get_db),
) -> Response:
    """
    Root endpoint - redirect to appropriate page.

    - If no users exist: redirect to /setup
    - If not authenticated: redirect to /login
    - If authenticated: redirect to /dashboard
    """
    # Check if any users exist
    user_count = db.query(User).count()

    if user_count == 0:
        return RedirectResponse(url="/setup", status_code=status.HTTP_302_FOUND)

    # Check if authenticated
    if not access_token:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    try:
        user_id = get_current_user_id_from_token(access_token)
        user = db.query(User).filter(User.id == user_id).first()

        if user and user.is_active:
            return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    except TokenError:
        pass

    # Not authenticated or invalid token
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


# ============================================================================
# LOGIN PAGE
# ============================================================================


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(
    request: Request,
    access_token: Annotated[str | None, Cookie()] = None,
    db: Session = Depends(get_db),
) -> Response:
    """
    Display login page.

    If already authenticated, redirect to dashboard.
    """
    # Check if any users exist
    user_count = db.query(User).count()

    if user_count == 0:
        return RedirectResponse(url="/setup", status_code=status.HTTP_302_FOUND)

    # Check if already authenticated
    if access_token:
        try:
            user_id = get_current_user_id_from_token(access_token)
            user = db.query(User).filter(User.id == user_id).first()

            if user and user.is_active:
                return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
        except TokenError:
            pass

    return templates.TemplateResponse(
        "auth/login.html",
        {"request": request},
    )


# ============================================================================
# SETUP WIZARD
# ============================================================================


@router.get("/setup", response_class=HTMLResponse, include_in_schema=False)
async def setup_wizard(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """
    Setup wizard landing page.

    Only accessible when no users exist. Shows welcome page.
    """
    # Check if users already exist
    user_count = db.query(User).count()

    if user_count > 0:
        logger.warning("setup_wizard_access_denied", reason="users_exist")
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

    return templates.TemplateResponse(
        "setup/welcome.html",
        {"request": request, "app_name": settings.app_name},
    )


@router.get("/setup/admin", response_class=HTMLResponse, include_in_schema=False)
async def setup_admin_page(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """
    Setup wizard - admin account creation page.
    """
    # Check if users already exist
    user_count = db.query(User).count()

    if user_count > 0:
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

    return templates.TemplateResponse(
        "setup/admin.html",
        {"request": request, "app_name": settings.app_name},
    )


@router.post("/setup/admin", include_in_schema=False)
async def setup_admin_create(
    request: Request,
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
) -> Response:
    """
    Create admin account (first user).
    """
    # Check if users already exist
    user_count = db.query(User).count()

    if user_count > 0:
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

    # Validate passwords match
    if password != confirm_password:
        return templates.TemplateResponse(
            "setup/admin.html",
            {
                "request": request,
                "app_name": settings.app_name,
                "error": "Passwords do not match",
                "username": username,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    password_errors = []
    if len(password) < 12:
        password_errors.append("Password must be at least 12 characters long")
    elif len(password) > 128:
        password_errors.append("Password must not exceed 128 characters")
    elif not re.search(r"[a-z]", password):
        password_errors.append("Password must contain at least one lowercase letter")
    elif not re.search(r"[A-Z]", password):
        password_errors.append("Password must contain at least one uppercase letter")
    elif not re.search(r"[0-9]", password):
        password_errors.append("Password must contain at least one digit")
    elif not re.search(r'[!@#$%^&*(),.?":{}|<>_\-+=\[\]\\;/`~]', password):
        password_errors.append("Password must contain at least one special character")

    if password_errors:
        return templates.TemplateResponse(
            "setup/admin.html",
            {
                "request": request,
                "app_name": settings.app_name,
                "error": password_errors[0],
                "username": username,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        # Hash password
        password_hash = hash_password(password)

        # Create user
        user = User(
            username=username.lower(),
            password_hash=password_hash,
            is_active=True,
            is_superuser=True,
        )

        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            # Race condition: another request created a user concurrently (CRIT-02)
            db.rollback()
            logger.warning("setup_admin_race_condition", username=username)
            return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

        db.refresh(user)

        # Post-commit race condition check: verify we are the ONLY user (CRIT-02).
        # Catches concurrent requests with different usernames.
        final_user_count = db.query(User).count()
        if final_user_count > 1:
            db.delete(user)
            db.commit()
            logger.warning("setup_admin_race_concurrent", username=username)
            return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

        logger.info("setup_admin_created", user_id=user.id, username=user.username)

        # Create auth tokens and set cookies
        access_token = create_access_token(user.id, user.username)
        refresh_token, _ = create_refresh_token(
            db=db,
            user_id=user.id,
            device_info=request.headers.get("User-Agent", "unknown"),
            ip_address=request.client.host if request.client else "unknown",
        )

        # Redirect to instance setup
        redirect_response = RedirectResponse(
            url="/setup/instance",
            status_code=status.HTTP_302_FOUND,
        )
        set_auth_cookies(redirect_response, access_token, refresh_token)

        return redirect_response

    except Exception as e:
        db.rollback()
        logger.error("setup_admin_failed", error=str(e))
        return templates.TemplateResponse(
            "setup/admin.html",
            {
                "request": request,
                "app_name": settings.app_name,
                "error": "Failed to create admin account. Please try again.",
                "username": username,
            },
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.get("/setup/instance", response_class=HTMLResponse, include_in_schema=False)
async def setup_instance_page(
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie),
) -> Response:
    """
    Setup wizard - first instance configuration page.
    """
    return templates.TemplateResponse(
        "setup/instance.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "user": current_user,
            "no_sidebar": True,
        },
    )


@router.post("/setup/instance", include_in_schema=False)
async def setup_instance_create(
    request: Request,
    instance_type: str = Form(...),
    name: str = Form(...),
    url: str = Form(...),
    api_key: str = Form(...),
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> Response:
    """
    Create first instance.
    """
    try:
        # Validate instance type
        if instance_type not in ["sonarr", "radarr"]:
            return templates.TemplateResponse(
                "setup/instance.html",
                {
                    "request": request,
                    "app_name": settings.app_name,
                    "user": current_user,
                    "no_sidebar": True,
                    "error": "Invalid instance type",
                    "name": name,
                    "url": url,
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            validate_instance_url(url, allow_local=settings.allow_local_instances)
        except (SSRFError, ValueError):
            return templates.TemplateResponse(
                "setup/instance.html",
                {
                    "request": request,
                    "app_name": settings.app_name,
                    "user": current_user,
                    "no_sidebar": True,
                    "error": "URL blocked for security reasons. Use a public hostname or enable local instances.",
                    "name": name,
                    "url": url,
                    "instance_type": instance_type,
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            if instance_type == "sonarr":
                async with SonarrClient(url, api_key) as client:
                    await client.get_system_status()
            else:
                async with RadarrClient(url, api_key) as client:
                    await client.get_system_status()
        except (SonarrError, RadarrError):
            return templates.TemplateResponse(
                "setup/instance.html",
                {
                    "request": request,
                    "app_name": settings.app_name,
                    "user": current_user,
                    "no_sidebar": True,
                    "error": "Connection test failed. Check the URL and API key. If running inside Docker, see the networking tip below.",
                    "name": name,
                    "url": url,
                    "instance_type": instance_type,
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        encrypted_api_key = encrypt_field(api_key)

        # Create instance
        instance = Instance(
            user_id=current_user.id,
            name=name,
            instance_type=instance_type,
            url=url,
            api_key=encrypted_api_key,
            is_active=True,
        )

        db.add(instance)
        db.commit()
        db.refresh(instance)

        logger.info(
            "setup_instance_created",
            instance_id=instance.id,
            user_id=current_user.id,
            instance_type=instance_type,
        )

        # Redirect to completion page
        return RedirectResponse(
            url="/setup/complete",
            status_code=status.HTTP_302_FOUND,
        )

    except Exception as e:
        db.rollback()
        logger.error("setup_instance_failed", error=str(e))
        return templates.TemplateResponse(
            "setup/instance.html",
            {
                "request": request,
                "app_name": settings.app_name,
                "user": current_user,
                "error": "Failed to create instance. Please try again.",
                "name": name,
                "url": url,
                "instance_type": instance_type,
            },
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.get("/setup/instance/skip", response_class=HTMLResponse, include_in_schema=False)
async def setup_instance_skip(
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie),
) -> Response:
    """
    Skip instance configuration during setup.

    Allows user to complete setup without adding an instance.
    They can add instances later from the dashboard.
    """
    logger.info("setup_instance_skipped", user_id=current_user.id)
    return RedirectResponse(
        url="/setup/complete",
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/setup/complete", response_class=HTMLResponse, include_in_schema=False)
async def setup_complete(
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie),
) -> Response:
    """
    Setup wizard - completion page.
    """
    return templates.TemplateResponse(
        "setup/complete.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "user": current_user,
            "no_sidebar": True,
        },
    )


# ============================================================================
# DASHBOARD PAGES
# ============================================================================


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_index(
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> Response:
    """
    Main dashboard page with overview statistics.
    """
    # Get statistics
    stats = await get_dashboard_stats(db, current_user)

    # Get recent activity (joinedload prevents N+1 lazy loads on search.instance.name)
    recent_searches = (
        db.query(SearchHistory)
        .options(joinedload(SearchHistory.instance))
        .join(Instance)
        .filter(Instance.user_id == current_user.id)
        .order_by(SearchHistory.started_at.desc())
        .limit(10)
        .all()
    )

    # Get instances for system status
    instances = (
        db.query(Instance)
        .filter(Instance.user_id == current_user.id)
        .order_by(Instance.created_at.desc())
        .all()
    )

    return templates.TemplateResponse(
        "dashboard/index.html",
        {
            "request": request,
            "user": current_user,
            "stats": stats,
            "recent_searches": recent_searches,
            "instances": instances,
            "active_page": "dashboard",
        },
    )


@router.get("/dashboard/instances", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_instances(
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> Response:
    """
    Instance management page.
    """
    instances = (
        db.query(Instance)
        .filter(Instance.user_id == current_user.id)
        .order_by(Instance.created_at.desc())
        .all()
    )

    return templates.TemplateResponse(
        "dashboard/instances.html",
        {
            "request": request,
            "user": current_user,
            "instances": instances,
            "active_page": "instances",
        },
    )


@router.post("/dashboard/instances/add", include_in_schema=False)
async def dashboard_add_instance(
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
    instance_type: str = Form(...),
    name: str = Form(...),
    url: str = Form(...),
    api_key: str = Form(...),
) -> Response:
    """Add a new instance from the dashboard."""
    if instance_type not in ("sonarr", "radarr"):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": "Invalid instance type. Must be 'sonarr' or 'radarr'."},
        )

    try:
        validate_instance_url(url, allow_local=settings.allow_local_instances)
    except (SSRFError, ValueError) as e:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": str(e)},
        )

    try:
        encrypted_api_key = encrypt_field(api_key)

        instance = Instance(
            user_id=current_user.id,
            name=name,
            instance_type=instance_type,
            url=url,
            api_key=encrypted_api_key,
            is_active=True,
        )

        db.add(instance)
        db.commit()

        logger.info(
            "dashboard_instance_created",
            instance_id=instance.id,
            user_id=current_user.id,
            instance_type=instance_type,
        )

        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={"detail": "Instance created successfully"},
        )

    except Exception as e:
        logger.error("dashboard_add_instance_failed", error=str(e))
        db.rollback()
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Failed to create instance. Please try again."},
        )


@router.get("/dashboard/search-queues", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_search_queues(
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> Response:
    """
    Search queue management page.
    """
    queues = (
        db.query(SearchQueue)
        .join(Instance)
        .filter(Instance.user_id == current_user.id)
        .order_by(SearchQueue.created_at.desc())
        .all()
    )

    # Get instances for create form
    instances = (
        db.query(Instance)
        .filter(Instance.user_id == current_user.id, Instance.is_active == True)  # noqa: E712
        .all()
    )

    return templates.TemplateResponse(
        "dashboard/search_queues.html",
        {
            "request": request,
            "user": current_user,
            "queues": queues,
            "instances": instances,
            "active_page": "queues",
        },
    )


@router.get(
    "/dashboard/search-queues/{queue_id}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def dashboard_search_queue_detail(
    request: Request,
    queue_id: int,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> Response:
    """
    Search queue detail page.
    """
    queue = (
        db.query(SearchQueue)
        .join(Instance)
        .filter(
            SearchQueue.id == queue_id,
            Instance.user_id == current_user.id,
        )
        .first()
    )

    if not queue:
        return RedirectResponse(url="/dashboard/search-queues", status_code=status.HTTP_302_FOUND)

    # Get recent history for this queue
    history = (
        db.query(SearchHistory)
        .filter(SearchHistory.search_queue_id == queue_id)
        .order_by(SearchHistory.started_at.desc())
        .limit(20)
        .all()
    )

    return templates.TemplateResponse(
        "dashboard/search_queue_detail.html",
        {
            "request": request,
            "user": current_user,
            "queue": queue,
            "history": history,
            "active_page": "queues",
        },
    )


@router.get("/dashboard/search-history", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_search_history(
    request: Request,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> Response:
    """
    Search history page with pagination.
    """
    # Calculate offset
    offset = (page - 1) * per_page

    # Get total count
    total_count = (
        db.query(SearchHistory).join(Instance).filter(Instance.user_id == current_user.id).count()
    )

    # Get paginated history
    history = (
        db.query(SearchHistory)
        .join(Instance)
        .filter(Instance.user_id == current_user.id)
        .order_by(SearchHistory.started_at.desc())
        .offset(offset)
        .limit(per_page)
        .all()
    )

    # Calculate pagination
    total_pages = (total_count + per_page - 1) // per_page

    return templates.TemplateResponse(
        "dashboard/search_history.html",
        {
            "request": request,
            "user": current_user,
            "history": history,
            "page": page,
            "per_page": per_page,
            "total_count": total_count,
            "total_pages": total_pages,
            "active_page": "history",
        },
    )


@router.get("/dashboard/settings", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_settings(
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie),
) -> Response:
    """
    User settings page.
    """
    return templates.TemplateResponse(
        "dashboard/settings.html",
        {
            "request": request,
            "user": current_user,
            "active_page": "settings",
        },
    )


# ============================================================================
# DASHBOARD API ENDPOINTS (JSON)
# ============================================================================


async def get_dashboard_stats(db: Session, user: User) -> dict[str, Any]:
    """
    Get dashboard statistics for a user.

    Returns:
        dict: Statistics including instance health, queue status, and search metrics
    """
    # Instance statistics
    total_instances = db.query(Instance).filter(Instance.user_id == user.id).count()

    active_instances = (
        db.query(Instance)
        .filter(Instance.user_id == user.id, Instance.is_active == True)  # noqa: E712
        .count()
    )

    # Search queue statistics
    total_queues = db.query(SearchQueue).join(Instance).filter(Instance.user_id == user.id).count()

    active_queues = (
        db.query(SearchQueue)
        .join(Instance)
        .filter(
            Instance.user_id == user.id,
            SearchQueue.is_active == True,  # noqa: E712
            SearchQueue.status.in_(["pending", "in_progress"]),
        )
        .count()
    )

    # Search history statistics
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = today - timedelta(days=7)

    searches_today = (
        db.query(SearchHistory)
        .join(Instance)
        .filter(Instance.user_id == user.id, SearchHistory.started_at >= today)
        .count()
    )

    searches_this_week = (
        db.query(SearchHistory)
        .join(Instance)
        .filter(Instance.user_id == user.id, SearchHistory.started_at >= week_ago)
        .count()
    )

    # Success rate
    successful_searches = (
        db.query(SearchHistory)
        .join(Instance)
        .filter(
            Instance.user_id == user.id,
            SearchHistory.status.in_(["success", "partial_success"]),
            SearchHistory.started_at >= week_ago,
        )
        .count()
    )

    success_rate = (successful_searches / searches_this_week * 100) if searches_this_week > 0 else 0

    return {
        "instances": {
            "total": total_instances,
            "active": active_instances,
            "inactive": total_instances - active_instances,
        },
        "search_queues": {
            "total": total_queues,
            "active": active_queues,
            "paused": total_queues - active_queues,
        },
        "searches": {
            "today": searches_today,
            "this_week": searches_this_week,
            "success_rate": round(success_rate, 1),
        },
    }


@router.get("/api/dashboard/stats", include_in_schema=False)
async def api_dashboard_stats(
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Get dashboard statistics (JSON API).

    Used for AJAX updates without page refresh.
    """
    stats = await get_dashboard_stats(db, current_user)
    return JSONResponse(content=stats)


@router.get("/api/dashboard/activity", include_in_schema=False)
async def api_dashboard_activity(
    limit: int = Query(10, ge=1, le=100),
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Get recent activity (JSON API).

    Used for AJAX updates without page refresh.
    """
    recent_searches = (
        db.query(SearchHistory)
        .options(joinedload(SearchHistory.instance))
        .join(Instance)
        .filter(Instance.user_id == current_user.id)
        .order_by(SearchHistory.started_at.desc())
        .limit(limit)
        .all()
    )

    activity = []
    for search in recent_searches:
        activity.append(
            {
                "id": search.id,
                "instance_name": search.instance.name,
                "strategy": search.strategy,
                "status": search.status,
                "items_searched": search.items_searched,
                "items_found": search.items_found,
                "started_at": search.started_at.isoformat() if search.started_at else None,
                "completed_at": search.completed_at.isoformat() if search.completed_at else None,
            }
        )

    return JSONResponse(content={"activity": activity})


@router.get("/api/dashboard/system-status", include_in_schema=False)
async def api_dashboard_system_status(
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """
    Get instance health status (JSON API).

    Returns per-instance health info for the system status panel.
    """
    instances = (
        db.query(Instance)
        .filter(Instance.user_id == current_user.id)
        .order_by(Instance.created_at.desc())
        .all()
    )

    instance_status = []
    for inst in instances:
        instance_status.append(
            {
                "id": inst.id,
                "name": inst.name,
                "instance_type": inst.instance_type,
                "url": inst.sanitized_url,
                "connection_status": inst.connection_status,
                "last_connection_test": (
                    inst.last_connection_test.isoformat() if inst.last_connection_test else None
                ),
            }
        )

    return JSONResponse(content={"instances": instance_status})
