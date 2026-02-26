"""
Search Scheduler Service for Vibe-Quality-Searcharr.

This module implements the core search automation scheduler using APScheduler:
- Background job management for search queues
- Multiple search strategies (round-robin, priority, aging, recent)
- Rate limit enforcement and cooldown tracking
- Job persistence across restarts
- Graceful lifecycle management (start/stop/pause/resume)
- Error handling and retry logic

The scheduler orchestrates automated searches across Sonarr/Radarr instances,
respecting rate limits and preventing duplicate searches within cooldown periods.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any

import structlog
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session

from vibe_quality_searcharr.database import get_engine
from vibe_quality_searcharr.models import SearchQueue
from vibe_quality_searcharr.services.search_queue import SearchQueueManager

logger = structlog.get_logger()


class SearchSchedulerError(Exception):
    """Base exception for search scheduler errors."""

    pass


class SearchScheduler:
    """
    Background search scheduler using APScheduler.

    Manages automated search execution across all active search queues:
    - Schedules jobs based on queue configuration
    - Executes searches using appropriate strategy
    - Enforces rate limits and cooldown periods
    - Tracks execution history and statistics
    - Persists job state to database for crash recovery
    """

    def __init__(self, db_session_factory: Callable[[], Session]):
        """
        Initialize search scheduler.

        Args:
            db_session_factory: Factory function to create database sessions
        """
        self.db_session_factory = db_session_factory
        self.scheduler: AsyncIOScheduler | None = None
        self.queue_manager: SearchQueueManager | None = None
        self._running = False
        self._paused = False

        logger.info("search_scheduler_initialized")

    def _create_scheduler(self) -> AsyncIOScheduler:
        """
        Create and configure APScheduler instance.

        Returns:
            AsyncIOScheduler: Configured scheduler instance
        """
        # Job store for persistence (use same database engine as app)
        # IMPORTANT: Use get_engine() to get our configured engine with SQLCipher support
        # Do NOT pass url= as it would create a separate engine without encryption
        jobstores = {
            "default": SQLAlchemyJobStore(
                engine=get_engine(),
                tablename="apscheduler_jobs",
            )
        }

        # Executor configuration
        executors = {
            "default": AsyncIOExecutor(),
        }

        # Job defaults
        job_defaults = {
            "coalesce": True,  # Combine missed runs into one
            "max_instances": 1,  # Only one instance of each job at a time
            "misfire_grace_time": 300,  # 5 minutes grace for missed jobs
        }

        scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
            timezone="UTC",
        )

        # Register event listeners
        scheduler.add_listener(
            self._job_executed_listener,
            EVENT_JOB_EXECUTED,
        )
        scheduler.add_listener(
            self._job_error_listener,
            EVENT_JOB_ERROR,
        )

        logger.info("apscheduler_created", jobstores=list(jobstores.keys()))
        return scheduler

    def _job_executed_listener(self, event: Any) -> None:
        """
        Handle successful job execution events.

        Args:
            event: APScheduler job execution event
        """
        logger.info(
            "scheduler_job_executed",
            job_id=event.job_id,
            scheduled_run_time=event.scheduled_run_time,
        )

    def _job_error_listener(self, event: Any) -> None:
        """
        Handle job execution error events.

        Args:
            event: APScheduler job error event
        """
        logger.error(
            "scheduler_job_error",
            job_id=event.job_id,
            exception=str(event.exception),
            traceback=event.traceback,
        )

    async def start(self) -> None:
        """
        Start the search scheduler.

        Initializes scheduler, loads existing queues, and starts background processing.

        Raises:
            SearchSchedulerError: If scheduler is already running or startup fails
        """
        if self._running:
            raise SearchSchedulerError("Scheduler is already running")

        try:
            logger.info("search_scheduler_starting")

            # Create scheduler instance
            self.scheduler = self._create_scheduler()

            # Initialize queue manager
            self.queue_manager = SearchQueueManager(self.db_session_factory)

            # Start scheduler
            self.scheduler.start()
            self._running = True

            # Load existing queues and schedule jobs
            await self._load_existing_queues()

            logger.info("search_scheduler_started", jobs_count=len(self.scheduler.get_jobs()))

        except Exception as e:
            logger.error("search_scheduler_start_failed", error=str(e))
            self._running = False
            raise SearchSchedulerError(f"Failed to start scheduler: {e}") from e

    async def stop(self, wait: bool = True) -> None:
        """
        Stop the search scheduler gracefully.

        Args:
            wait: Whether to wait for running jobs to complete (default: True)

        Raises:
            SearchSchedulerError: If scheduler is not running
        """
        if not self._running:
            raise SearchSchedulerError("Scheduler is not running")

        try:
            logger.info("search_scheduler_stopping", wait=wait)

            if self.scheduler:
                self.scheduler.shutdown(wait=wait)

            self._running = False
            self._paused = False

            logger.info("search_scheduler_stopped")

        except Exception as e:
            logger.error("search_scheduler_stop_failed", error=str(e))
            raise SearchSchedulerError(f"Failed to stop scheduler: {e}") from e

    async def pause(self) -> None:
        """
        Pause the scheduler (stop accepting new jobs).

        Raises:
            SearchSchedulerError: If scheduler is not running or already paused
        """
        if not self._running:
            raise SearchSchedulerError("Scheduler is not running")

        if self._paused:
            raise SearchSchedulerError("Scheduler is already paused")

        try:
            if self.scheduler:
                self.scheduler.pause()
                self._paused = True
                logger.info("search_scheduler_paused")

        except Exception as e:
            logger.error("search_scheduler_pause_failed", error=str(e))
            raise SearchSchedulerError(f"Failed to pause scheduler: {e}") from e

    async def resume(self) -> None:
        """
        Resume the scheduler after pausing.

        Raises:
            SearchSchedulerError: If scheduler is not running or not paused
        """
        if not self._running:
            raise SearchSchedulerError("Scheduler is not running")

        if not self._paused:
            raise SearchSchedulerError("Scheduler is not paused")

        try:
            if self.scheduler:
                self.scheduler.resume()
                self._paused = False
                logger.info("search_scheduler_resumed")

        except Exception as e:
            logger.error("search_scheduler_resume_failed", error=str(e))
            raise SearchSchedulerError(f"Failed to resume scheduler: {e}") from e

    async def _load_existing_queues(self) -> None:
        """
        Load existing search queues from database and schedule them.

        This is called on startup to restore scheduled jobs after restart.
        """
        try:
            db = self.db_session_factory()
            try:
                # Get all active queues
                queues = db.query(SearchQueue).filter(SearchQueue.is_active == True).all()

                logger.info("loading_existing_queues", count=len(queues))

                for queue in queues:
                    await self.schedule_queue(queue.id, reschedule=False)

                logger.info("existing_queues_loaded", scheduled_count=len(queues))

            finally:
                db.close()

        except Exception as e:
            logger.error("failed_to_load_existing_queues", error=str(e))
            raise

    async def schedule_queue(self, queue_id: int, reschedule: bool = False) -> None:
        """
        Schedule a search queue for execution.

        Args:
            queue_id: ID of the search queue to schedule
            reschedule: Whether to reschedule if already scheduled (default: False)

        Raises:
            SearchSchedulerError: If scheduler is not running or scheduling fails
        """
        if not self._running or not self.scheduler:
            raise SearchSchedulerError("Scheduler is not running")

        try:
            db = self.db_session_factory()
            try:
                queue = db.query(SearchQueue).filter(SearchQueue.id == queue_id).first()

                if not queue:
                    raise SearchSchedulerError(f"Search queue {queue_id} not found")

                if not queue.is_active:
                    logger.warning("queue_not_active", queue_id=queue_id)
                    return

                # Generate unique job ID
                job_id = f"search_queue_{queue_id}"

                # Remove existing job if rescheduling
                if reschedule and self.scheduler.get_job(job_id):
                    self.scheduler.remove_job(job_id)
                    logger.info("removed_existing_job", job_id=job_id)

                # Calculate next run time
                run_time = queue.next_run or datetime.utcnow()

                # Schedule job
                if queue.is_recurring and queue.interval_hours:
                    # Recurring job with interval
                    self.scheduler.add_job(
                        self._execute_search_queue,
                        trigger="interval",
                        hours=queue.interval_hours,
                        id=job_id,
                        args=[queue_id],
                        next_run_time=run_time,
                        replace_existing=True,
                    )
                    logger.info(
                        "scheduled_recurring_queue",
                        queue_id=queue_id,
                        interval_hours=queue.interval_hours,
                        next_run=run_time,
                    )
                else:
                    # One-time job
                    self.scheduler.add_job(
                        self._execute_search_queue,
                        trigger="date",
                        run_date=run_time,
                        id=job_id,
                        args=[queue_id],
                        replace_existing=True,
                    )
                    logger.info(
                        "scheduled_onetime_queue",
                        queue_id=queue_id,
                        run_date=run_time,
                    )

            finally:
                db.close()

        except Exception as e:
            logger.error("failed_to_schedule_queue", queue_id=queue_id, error=str(e))
            raise SearchSchedulerError(f"Failed to schedule queue {queue_id}: {e}") from e

    async def unschedule_queue(self, queue_id: int) -> None:
        """
        Unschedule a search queue (remove from scheduler).

        Args:
            queue_id: ID of the search queue to unschedule

        Raises:
            SearchSchedulerError: If scheduler is not running
        """
        if not self._running or not self.scheduler:
            raise SearchSchedulerError("Scheduler is not running")

        try:
            job_id = f"search_queue_{queue_id}"

            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
                logger.info("unscheduled_queue", queue_id=queue_id)
            else:
                logger.warning("queue_not_scheduled", queue_id=queue_id)

        except Exception as e:
            logger.error("failed_to_unschedule_queue", queue_id=queue_id, error=str(e))
            raise SearchSchedulerError(f"Failed to unschedule queue {queue_id}: {e}") from e

    async def _execute_search_queue(self, queue_id: int) -> None:
        """
        Execute a search queue (job handler).

        This is called by APScheduler when a job is triggered.

        Args:
            queue_id: ID of the search queue to execute
        """
        logger.info("executing_search_queue", queue_id=queue_id)

        try:
            if not self.queue_manager:
                raise SearchSchedulerError("Queue manager not initialized")

            # Execute the search using queue manager
            result = await self.queue_manager.execute_queue(queue_id)

            logger.info(
                "search_queue_executed",
                queue_id=queue_id,
                status=result.get("status"),
                items_searched=result.get("items_searched", 0),
                items_found=result.get("items_found", 0),
            )

            # If queue was one-time, mark as completed and unschedule
            db = self.db_session_factory()
            try:
                queue = db.query(SearchQueue).filter(SearchQueue.id == queue_id).first()
                if queue and not queue.is_recurring:
                    await self.unschedule_queue(queue_id)

            finally:
                db.close()

        except Exception as e:
            logger.error("search_queue_execution_failed", queue_id=queue_id, error=str(e))

            # Update queue with error
            db = self.db_session_factory()
            try:
                queue = db.query(SearchQueue).filter(SearchQueue.id == queue_id).first()
                if queue:
                    queue.mark_failed(str(e))
                    db.commit()

            finally:
                db.close()

    def get_status(self) -> dict[str, Any]:
        """
        Get scheduler status and statistics.

        Returns:
            dict: Scheduler status information including:
                - running: bool
                - paused: bool
                - jobs_count: int
                - jobs: list of job details
        """
        if not self._running or not self.scheduler:
            return {
                "running": False,
                "paused": False,
                "jobs_count": 0,
                "jobs": [],
            }

        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                    "trigger": str(job.trigger),
                }
            )

        return {
            "running": self._running,
            "paused": self._paused,
            "jobs_count": len(jobs),
            "jobs": jobs,
        }


# Global scheduler instance (singleton)
_scheduler_instance: SearchScheduler | None = None


def get_scheduler(db_session_factory: Callable[[], Session]) -> SearchScheduler:
    """
    Get or create the global scheduler instance.

    Args:
        db_session_factory: Factory function to create database sessions

    Returns:
        SearchScheduler: Global scheduler instance
    """
    global _scheduler_instance

    if _scheduler_instance is None:
        _scheduler_instance = SearchScheduler(db_session_factory)

    return _scheduler_instance


async def start_scheduler(db_session_factory: Callable[[], Session]) -> None:
    """
    Start the global scheduler instance.

    This should be called during application startup.

    Args:
        db_session_factory: Factory function to create database sessions
    """
    scheduler = get_scheduler(db_session_factory)
    await scheduler.start()


async def stop_scheduler() -> None:
    """
    Stop the global scheduler instance.

    This should be called during application shutdown.
    """
    global _scheduler_instance

    if _scheduler_instance:
        await _scheduler_instance.stop()
