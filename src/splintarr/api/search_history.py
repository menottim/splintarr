"""
Search History API endpoints for Splintarr.

This module provides REST API endpoints for search history:
- History retrieval and filtering
- Statistics and analytics
- History cleanup operations
"""

from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from splintarr.api.auth import get_current_user
from splintarr.database import get_db, get_session_factory
from splintarr.models import Instance, SearchQueue, User
from splintarr.schemas import MessageResponse, SearchHistoryResponse
from splintarr.services import get_history_service

logger = structlog.get_logger()

limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/api/search-history", tags=["search-history"])


@router.get(
    "",
    response_model=list[SearchHistoryResponse],
    summary="List search history",
    description="Get search execution history with optional filtering",
)
@limiter.limit("30/minute")
async def list_search_history(
    request: Request,
    instance_id: int | None = Query(None, description="Filter by instance ID"),
    queue_id: int | None = Query(None, description="Filter by queue ID"),
    strategy: str | None = Query(None, description="Filter by strategy"),
    status: str | None = Query(None, description="Filter by status"),
    start_date: datetime | None = Query(None, description="Filter by start date (>=)"),
    end_date: datetime | None = Query(None, description="Filter by end date (<=)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of records"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    List search history with filtering.

    Returns search execution history for the current user's instances.
    """
    try:
        # Get user's instance IDs
        user_instance_ids = [
            i.id for i in db.query(Instance).filter(Instance.user_id == current_user.id).all()
        ]

        # If instance_id filter is provided, verify it belongs to user
        if instance_id is not None and instance_id not in user_instance_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this instance",
            )

        # Get history service
        history_service = get_history_service(get_session_factory())

        # If no instance_id filter, get history for all user instances
        if instance_id is None:
            # For multiple instances, we need to query each separately and combine
            # This is a simplification; in production you'd optimize this
            all_history = []
            for iid in user_instance_ids:
                history = history_service.get_history(
                    instance_id=iid,
                    queue_id=queue_id,
                    strategy=strategy,
                    status=status,
                    start_date=start_date,
                    end_date=end_date,
                    limit=limit,
                    offset=offset,
                )
                all_history.extend(history)

            # Sort by most recent first
            all_history.sort(key=lambda h: h.started_at, reverse=True)

            # Apply limit
            all_history = all_history[:limit]
        else:
            # Single instance query
            all_history = history_service.get_history(
                instance_id=instance_id,
                queue_id=queue_id,
                strategy=strategy,
                status=status,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
                offset=offset,
            )

        return [
            SearchHistoryResponse(
                id=h.id,
                instance_id=h.instance_id,
                search_queue_id=h.search_queue_id,
                search_name=h.search_name,
                strategy=h.strategy,
                started_at=h.started_at,
                completed_at=h.completed_at,
                duration_seconds=h.duration_seconds,
                status=h.status,
                items_searched=h.items_searched,
                items_found=h.items_found,
                searches_triggered=h.searches_triggered,
                error_message=h.error_message,
            )
            for h in all_history
        ]

    except HTTPException:
        raise
    except Exception as e:
        logger.error("list_search_history_failed", error=str(e), user_id=current_user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list search history",
        )


@router.get(
    "/stats",
    response_model=dict[str, Any],
    summary="Get search statistics",
    description="Get aggregated search statistics and metrics",
)
@limiter.limit("30/minute")
async def get_search_statistics(
    request: Request,
    instance_id: int | None = Query(None, description="Filter by instance ID"),
    queue_id: int | None = Query(None, description="Filter by queue ID"),
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Get search statistics and analytics.

    Returns aggregated metrics including success rates, items found, and trends.
    """
    try:
        # Get user's instance IDs
        user_instance_ids = [
            i.id for i in db.query(Instance).filter(Instance.user_id == current_user.id).all()
        ]

        # If instance_id filter is provided, verify it belongs to user
        if instance_id is not None and instance_id not in user_instance_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this instance",
            )

        # Get history service
        history_service = get_history_service(get_session_factory())

        # Get statistics
        stats = history_service.get_statistics(
            instance_id=instance_id,
            queue_id=queue_id,
            days=days,
        )

        return stats

    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_search_statistics_failed", error=str(e), user_id=current_user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get search statistics",
        )


@router.delete(
    "",
    response_model=MessageResponse,
    summary="Clean up old history",
    description="Delete search history older than specified days",
)
@limiter.limit("5/minute")
async def cleanup_search_history(
    request: Request,
    days: int = Query(90, ge=30, le=365, description="Delete history older than this many days"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Clean up old search history.

    Deletes history records older than the specified number of days.
    Minimum 30 days, maximum 365 days.
    """
    try:
        history_service = get_history_service(get_session_factory())

        # Clean up old history
        deleted_count = history_service.cleanup_old_history(days=days)

        logger.info(
            "search_history_cleaned_up",
            user_id=current_user.id,
            deleted_count=deleted_count,
            days=days,
        )

        return MessageResponse(
            message=f"Successfully deleted {deleted_count} history records older than {days} days"
        )

    except Exception as e:
        logger.error("cleanup_search_history_failed", error=str(e), user_id=current_user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clean up search history",
        )


@router.get(
    "/failures",
    response_model=list[SearchHistoryResponse],
    summary="Get recent failures",
    description="Get recent failed searches for troubleshooting",
)
@limiter.limit("30/minute")
async def get_recent_failures(
    request: Request,
    instance_id: int | None = Query(None, description="Filter by instance ID"),
    limit: int = Query(10, ge=1, le=50, description="Maximum number of failures to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Get recent search failures.

    Returns most recent failed searches for troubleshooting purposes.
    """
    try:
        # Get user's instance IDs
        user_instance_ids = [
            i.id for i in db.query(Instance).filter(Instance.user_id == current_user.id).all()
        ]

        # If instance_id filter is provided, verify it belongs to user
        if instance_id is not None and instance_id not in user_instance_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this instance",
            )

        # Get history service
        history_service = get_history_service(get_session_factory())

        # Get recent failures
        failures = history_service.get_recent_failures(
            instance_id=instance_id,
            limit=limit,
        )

        return [
            SearchHistoryResponse(
                id=h.id,
                instance_id=h.instance_id,
                search_queue_id=h.search_queue_id,
                search_name=h.search_name,
                strategy=h.strategy,
                started_at=h.started_at,
                completed_at=h.completed_at,
                duration_seconds=h.duration_seconds,
                status=h.status,
                items_searched=h.items_searched,
                items_found=h.items_found,
                searches_triggered=h.searches_triggered,
                error_message=h.error_message,
            )
            for h in failures
        ]

    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_recent_failures_failed", error=str(e), user_id=current_user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get recent failures",
        )


@router.get(
    "/queue/{queue_id}",
    response_model=list[SearchHistoryResponse],
    summary="Get queue history",
    description="Get search history for a specific queue",
)
@limiter.limit("30/minute")
async def get_queue_history(
    request: Request,
    queue_id: int,
    limit: int = Query(50, ge=1, le=500, description="Maximum number of records"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Get search history for a specific queue.

    Returns all history records for the specified queue.
    """
    try:
        queue = db.query(SearchQueue).filter(SearchQueue.id == queue_id).first()

        if not queue:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Search queue {queue_id} not found",
            )

        # Verify instance belongs to user
        instance = (
            db.query(Instance)
            .filter(
                Instance.id == queue.instance_id,
                Instance.user_id == current_user.id,
            )
            .first()
        )

        if not instance:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this search queue",
            )

        # Get history service
        history_service = get_history_service(get_session_factory())

        # Get queue history
        history = history_service.get_history(
            queue_id=queue_id,
            limit=limit,
            offset=offset,
        )

        return [
            SearchHistoryResponse(
                id=h.id,
                instance_id=h.instance_id,
                search_queue_id=h.search_queue_id,
                search_name=h.search_name,
                strategy=h.strategy,
                started_at=h.started_at,
                completed_at=h.completed_at,
                duration_seconds=h.duration_seconds,
                status=h.status,
                items_searched=h.items_searched,
                items_found=h.items_found,
                searches_triggered=h.searches_triggered,
                error_message=h.error_message,
            )
            for h in history
        ]

    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_queue_history_failed", error=str(e), queue_id=queue_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get queue history",
        )
