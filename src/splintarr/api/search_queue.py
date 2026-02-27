"""
Search Queue API endpoints for Splintarr.

This module provides REST API endpoints for managing search queues:
- CRUD operations for search queues
- Queue control (start, pause, resume)
- Status monitoring
- History retrieval
"""

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from splintarr.api.auth import get_current_user
from splintarr.database import get_db, get_session_factory
from splintarr.models import Instance, SearchQueue, User
from splintarr.schemas import (
    MessageResponse,
    SearchQueueCreate,
    SearchQueueResponse,
    SearchQueueUpdate,
)
from splintarr.services import SearchQueueManager, get_history_service, get_scheduler

logger = structlog.get_logger()

limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/api/search-queues", tags=["search-queues"])


@router.post(
    "",
    response_model=SearchQueueResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create search queue",
    description="Create a new search queue for automated searching",
)
@limiter.limit("10/minute")
async def create_search_queue(
    request: Request,
    queue_data: SearchQueueCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Create a new search queue.

    Requires authentication. Queue will be associated with an instance
    owned by the current user.
    """
    try:
        # Verify instance exists and belongs to user
        instance = (
            db.query(Instance)
            .filter(
                Instance.id == queue_data.instance_id,
                Instance.user_id == current_user.id,
            )
            .first()
        )

        if not instance:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Instance {queue_data.instance_id} not found or access denied",
            )

        # Create search queue
        queue = SearchQueue(
            instance_id=queue_data.instance_id,
            name=queue_data.name,
            strategy=queue_data.strategy,
            is_recurring=queue_data.recurring,
            interval_hours=queue_data.interval_hours,
            filters=queue_data.filters if queue_data.filters else None,
            status="pending",
            is_active=True,
        )

        # Schedule first run
        if queue.is_recurring and queue.interval_hours:
            queue.schedule_next_run()
        else:
            # One-time search, schedule for immediate execution
            queue.schedule_next_run(delay_hours=0)

        db.add(queue)
        db.commit()
        db.refresh(queue)

        logger.info(
            "search_queue_created",
            queue_id=queue.id,
            user_id=current_user.id,
            instance_id=queue_data.instance_id,
            strategy=queue_data.strategy,
        )

        # Schedule in scheduler
        try:
            scheduler = get_scheduler(get_session_factory())
            await scheduler.schedule_queue(queue.id)
        except Exception as e:
            logger.error("failed_to_schedule_queue", queue_id=queue.id, error=str(e))
            # Don't fail the request, queue is created but not scheduled

        return SearchQueueResponse(
            id=queue.id,
            instance_id=queue.instance_id,
            name=queue.name,
            strategy=queue.strategy,
            recurring=queue.is_recurring,
            interval_hours=queue.interval_hours,
            is_active=queue.is_active,
            status=queue.status,
            next_run=queue.next_run,
            last_run=queue.last_run,
            consecutive_failures=queue.consecutive_failures,
            created_at=queue.created_at,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("create_search_queue_failed", error=str(e), user_id=current_user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create search queue",
        )


@router.get(
    "",
    response_model=list[SearchQueueResponse],
    summary="List search queues",
    description="Get all search queues for the current user's instances",
)
@limiter.limit("30/minute")
async def list_search_queues(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    List all search queues for current user.

    Returns queues for all instances owned by the user.
    """
    try:
        # Get all instances for user
        user_instance_ids = [
            i.id for i in db.query(Instance).filter(Instance.user_id == current_user.id).all()
        ]

        # Get all queues for user's instances
        queues = (
            db.query(SearchQueue)
            .filter(SearchQueue.instance_id.in_(user_instance_ids))
            .order_by(SearchQueue.created_at.desc())
            .all()
        )

        return [
            SearchQueueResponse(
                id=q.id,
                instance_id=q.instance_id,
                name=q.name,
                strategy=q.strategy,
                recurring=q.is_recurring,
                interval_hours=q.interval_hours,
                is_active=q.is_active,
                status=q.status,
                next_run=q.next_run,
                last_run=q.last_run,
                consecutive_failures=q.consecutive_failures,
                created_at=q.created_at,
            )
            for q in queues
        ]

    except Exception as e:
        logger.error("list_search_queues_failed", error=str(e), user_id=current_user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list search queues",
        )


@router.get(
    "/{queue_id}",
    response_model=SearchQueueResponse,
    summary="Get search queue",
    description="Get details of a specific search queue",
)
@limiter.limit("60/minute")
async def get_search_queue(
    request: Request,
    queue_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Get search queue details.

    Returns queue information if it belongs to user's instance.
    """
    try:
        # Get queue and verify ownership
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

        return SearchQueueResponse(
            id=queue.id,
            instance_id=queue.instance_id,
            name=queue.name,
            strategy=queue.strategy,
            recurring=queue.is_recurring,
            interval_hours=queue.interval_hours,
            is_active=queue.is_active,
            status=queue.status,
            next_run=queue.next_run,
            last_run=queue.last_run,
            consecutive_failures=queue.consecutive_failures,
            created_at=queue.created_at,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_search_queue_failed", error=str(e), queue_id=queue_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get search queue",
        )


@router.put(
    "/{queue_id}",
    response_model=SearchQueueResponse,
    summary="Update search queue",
    description="Update search queue configuration",
)
@limiter.limit("20/minute")
async def update_search_queue(
    request: Request,
    queue_id: int,
    queue_data: SearchQueueUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Update search queue.

    Only provided fields will be updated. Requires queue to belong to user's instance.
    """
    try:
        # Get queue and verify ownership
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

        # Update fields
        if queue_data.name is not None:
            queue.name = queue_data.name

        if queue_data.strategy is not None:
            queue.strategy = queue_data.strategy

        if queue_data.recurring is not None:
            queue.is_recurring = queue_data.recurring

        if queue_data.interval_hours is not None:
            queue.interval_hours = queue_data.interval_hours

        if queue_data.is_active is not None:
            if queue_data.is_active and not queue.is_active:
                queue.activate()
            elif not queue_data.is_active and queue.is_active:
                queue.deactivate()

        if queue_data.filters is not None:
            queue.filters = queue_data.filters

        db.commit()
        db.refresh(queue)

        logger.info(
            "search_queue_updated",
            queue_id=queue_id,
            user_id=current_user.id,
        )

        # Reschedule if active
        if queue.is_active:
            try:
                scheduler = get_scheduler(get_session_factory())
                await scheduler.schedule_queue(queue.id, reschedule=True)
            except Exception as e:
                logger.error("failed_to_reschedule_queue", queue_id=queue.id, error=str(e))

        return SearchQueueResponse(
            id=queue.id,
            instance_id=queue.instance_id,
            name=queue.name,
            strategy=queue.strategy,
            recurring=queue.is_recurring,
            interval_hours=queue.interval_hours,
            is_active=queue.is_active,
            status=queue.status,
            next_run=queue.next_run,
            last_run=queue.last_run,
            consecutive_failures=queue.consecutive_failures,
            created_at=queue.created_at,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("update_search_queue_failed", error=str(e), queue_id=queue_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update search queue",
        )


@router.delete(
    "/{queue_id}",
    response_model=MessageResponse,
    summary="Delete search queue",
    description="Delete a search queue permanently",
)
@limiter.limit("10/minute")
async def delete_search_queue(
    request: Request,
    queue_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Delete search queue.

    Permanently removes queue and unschedules it from scheduler.
    """
    try:
        # Get queue and verify ownership
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

        # Unschedule from scheduler
        try:
            scheduler = get_scheduler(get_session_factory())
            await scheduler.unschedule_queue(queue_id)
        except Exception as e:
            logger.warning("failed_to_unschedule_queue", queue_id=queue_id, error=str(e))

        # Delete queue
        db.delete(queue)
        db.commit()

        logger.info(
            "search_queue_deleted",
            queue_id=queue_id,
            user_id=current_user.id,
        )

        return MessageResponse(message=f"Search queue {queue_id} deleted successfully")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("delete_search_queue_failed", error=str(e), queue_id=queue_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete search queue",
        )


@router.post(
    "/{queue_id}/start",
    response_model=MessageResponse,
    summary="Start search queue",
    description="Manually trigger search queue execution",
)
@limiter.limit("10/minute")
async def start_search_queue(
    request: Request,
    queue_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Start search queue immediately.

    Triggers immediate execution regardless of schedule.
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

        queue_manager = SearchQueueManager(get_session_factory())
        result = await queue_manager.execute_queue(queue_id)

        logger.info(
            "search_queue_started_manually",
            queue_id=queue_id,
            user_id=current_user.id,
            status=result.get("status"),
        )

        return MessageResponse(
            message=f"Search queue started: {result['status']} "
            f"({result['items_found']}/{result['items_searched']} items found)"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("start_search_queue_failed", error=str(e), queue_id=queue_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start search queue",
        )


@router.post(
    "/{queue_id}/pause",
    response_model=MessageResponse,
    summary="Pause search queue",
    description="Deactivate search queue (stops future executions)",
)
@limiter.limit("10/minute")
async def pause_search_queue(
    request: Request,
    queue_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Pause search queue.

    Deactivates queue to prevent future automatic executions.
    """
    try:
        # Get queue and verify ownership
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

        # Deactivate queue
        queue.deactivate()
        db.commit()

        # Unschedule from scheduler
        try:
            scheduler = get_scheduler(get_session_factory())
            await scheduler.unschedule_queue(queue_id)
        except Exception as e:
            logger.warning("failed_to_unschedule_queue", queue_id=queue_id, error=str(e))

        logger.info(
            "search_queue_paused",
            queue_id=queue_id,
            user_id=current_user.id,
        )

        return MessageResponse(message=f"Search queue {queue_id} paused successfully")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("pause_search_queue_failed", error=str(e), queue_id=queue_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to pause search queue",
        )


@router.post(
    "/{queue_id}/resume",
    response_model=MessageResponse,
    summary="Resume search queue",
    description="Reactivate paused search queue",
)
@limiter.limit("10/minute")
async def resume_search_queue(
    request: Request,
    queue_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Resume search queue.

    Reactivates paused queue and reschedules it.
    """
    try:
        # Get queue and verify ownership
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

        # Activate queue
        queue.activate()
        db.commit()

        # Reschedule in scheduler
        try:
            scheduler = get_scheduler(get_session_factory())
            await scheduler.schedule_queue(queue_id, reschedule=True)
        except Exception as e:
            logger.error("failed_to_reschedule_queue", queue_id=queue_id, error=str(e))

        logger.info(
            "search_queue_resumed",
            queue_id=queue_id,
            user_id=current_user.id,
        )

        return MessageResponse(message=f"Search queue {queue_id} resumed successfully")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("resume_search_queue_failed", error=str(e), queue_id=queue_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to resume search queue",
        )


@router.get(
    "/{queue_id}/status",
    response_model=dict[str, Any],
    summary="Get queue status",
    description="Get current status and statistics for a search queue",
)
@limiter.limit("30/minute")
async def get_queue_status(
    request: Request,
    queue_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Get queue status and performance metrics.

    Returns current status and recent performance statistics.
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

        history_service = get_history_service(get_session_factory())
        performance = history_service.get_queue_performance(queue_id, days=30)

        return {
            "queue_id": queue.id,
            "name": queue.name,
            "status": queue.status,
            "is_active": queue.is_active,
            "next_run": queue.next_run.isoformat() if queue.next_run else None,
            "last_run": queue.last_run.isoformat() if queue.last_run else None,
            "consecutive_failures": queue.consecutive_failures,
            "performance": performance,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_queue_status_failed", error=str(e), queue_id=queue_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get queue status",
        )
