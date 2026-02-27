"""
Unit tests for Search Scheduler Service.

Tests scheduler lifecycle, job management, and execution.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from splintarr.models import SearchQueue, Instance
from splintarr.services.scheduler import SearchScheduler, SearchSchedulerError


@pytest.fixture
def mock_db_session():
    """Mock database session."""
    session = MagicMock()
    session.query = MagicMock()
    session.commit = MagicMock()
    session.close = MagicMock()
    return session


@pytest.fixture
def mock_session_factory(mock_db_session):
    """Mock session factory."""
    return lambda: mock_db_session


@pytest.fixture
def scheduler(mock_session_factory):
    """Create scheduler instance."""
    return SearchScheduler(mock_session_factory)


class TestSchedulerLifecycle:
    """Test scheduler lifecycle operations."""

    @pytest.mark.asyncio
    async def test_start_scheduler(self, scheduler, mock_db_session):
        """Test starting the scheduler."""
        # Mock empty queue list
        mock_db_session.query.return_value.filter.return_value.all.return_value = []

        await scheduler.start()

        assert scheduler._running is True
        assert scheduler.scheduler is not None
        assert scheduler.queue_manager is not None

    @pytest.mark.asyncio
    async def test_start_scheduler_already_running(self, scheduler, mock_db_session):
        """Test starting scheduler when already running."""
        # Mock empty queue list
        mock_db_session.query.return_value.filter.return_value.all.return_value = []

        await scheduler.start()

        with pytest.raises(SearchSchedulerError, match="already running"):
            await scheduler.start()

    @pytest.mark.asyncio
    async def test_stop_scheduler(self, scheduler, mock_db_session):
        """Test stopping the scheduler."""
        # Mock empty queue list
        mock_db_session.query.return_value.filter.return_value.all.return_value = []

        await scheduler.start()
        await scheduler.stop(wait=False)

        assert scheduler._running is False

    @pytest.mark.asyncio
    async def test_stop_scheduler_not_running(self, scheduler):
        """Test stopping scheduler when not running."""
        with pytest.raises(SearchSchedulerError, match="not running"):
            await scheduler.stop()

    @pytest.mark.asyncio
    async def test_pause_scheduler(self, scheduler, mock_db_session):
        """Test pausing the scheduler."""
        # Mock empty queue list
        mock_db_session.query.return_value.filter.return_value.all.return_value = []

        await scheduler.start()
        await scheduler.pause()

        assert scheduler._paused is True

    @pytest.mark.asyncio
    async def test_resume_scheduler(self, scheduler, mock_db_session):
        """Test resuming the scheduler."""
        # Mock empty queue list
        mock_db_session.query.return_value.filter.return_value.all.return_value = []

        await scheduler.start()
        await scheduler.pause()
        await scheduler.resume()

        assert scheduler._paused is False


class TestJobScheduling:
    """Test job scheduling operations."""

    @pytest.mark.asyncio
    async def test_schedule_recurring_queue(self, scheduler, mock_db_session):
        """Test scheduling a recurring search queue."""
        # Mock empty queue list for startup
        mock_db_session.query.return_value.filter.return_value.all.return_value = []

        await scheduler.start()

        # Create mock queue
        queue = SearchQueue(
            id=1,
            instance_id=1,
            name="Test Queue",
            strategy="missing",
            is_recurring=True,
            interval_hours=24,
            is_active=True,
            status="pending",
        )
        queue.schedule_next_run()

        # Mock query to return queue
        mock_db_session.query.return_value.filter.return_value.first.return_value = queue

        await scheduler.schedule_queue(1)

        # Verify job was scheduled
        job = scheduler.scheduler.get_job("search_queue_1")
        assert job is not None

    @pytest.mark.asyncio
    async def test_schedule_onetime_queue(self, scheduler, mock_db_session):
        """Test scheduling a one-time search queue."""
        # Mock empty queue list for startup
        mock_db_session.query.return_value.filter.return_value.all.return_value = []

        await scheduler.start()

        # Create mock queue
        queue = SearchQueue(
            id=2,
            instance_id=1,
            name="One-time Queue",
            strategy="missing",
            is_recurring=False,
            interval_hours=None,
            is_active=True,
            status="pending",
        )
        queue.schedule_next_run(delay_hours=0)

        # Mock query to return queue
        mock_db_session.query.return_value.filter.return_value.first.return_value = queue

        await scheduler.schedule_queue(2)

        # Verify job was scheduled
        job = scheduler.scheduler.get_job("search_queue_2")
        assert job is not None

    @pytest.mark.asyncio
    async def test_unschedule_queue(self, scheduler, mock_db_session):
        """Test unscheduling a search queue."""
        # Mock empty queue list for startup
        mock_db_session.query.return_value.filter.return_value.all.return_value = []

        await scheduler.start()

        # Create and schedule queue
        queue = SearchQueue(
            id=1,
            instance_id=1,
            name="Test Queue",
            strategy="missing",
            is_recurring=True,
            interval_hours=24,
            is_active=True,
            status="pending",
        )
        queue.schedule_next_run()

        mock_db_session.query.return_value.filter.return_value.first.return_value = queue

        await scheduler.schedule_queue(1)

        # Unschedule
        await scheduler.unschedule_queue(1)

        # Verify job was removed
        job = scheduler.scheduler.get_job("search_queue_1")
        assert job is None

    @pytest.mark.asyncio
    async def test_reschedule_queue(self, scheduler, mock_db_session):
        """Test rescheduling an existing queue."""
        # Mock empty queue list for startup
        mock_db_session.query.return_value.filter.return_value.all.return_value = []

        await scheduler.start()

        # Create and schedule queue
        queue = SearchQueue(
            id=1,
            instance_id=1,
            name="Test Queue",
            strategy="missing",
            is_recurring=True,
            interval_hours=24,
            is_active=True,
            status="pending",
        )
        queue.schedule_next_run()

        mock_db_session.query.return_value.filter.return_value.first.return_value = queue

        await scheduler.schedule_queue(1)

        # Change interval and reschedule
        queue.interval_hours = 48
        await scheduler.schedule_queue(1, reschedule=True)

        # Verify job exists
        job = scheduler.scheduler.get_job("search_queue_1")
        assert job is not None


class TestSchedulerStatus:
    """Test scheduler status reporting."""

    @pytest.mark.asyncio
    async def test_get_status_not_running(self, scheduler):
        """Test getting status when scheduler is not running."""
        status = scheduler.get_status()

        assert status["running"] is False
        assert status["paused"] is False
        assert status["jobs_count"] == 0
        assert status["jobs"] == []

    @pytest.mark.asyncio
    async def test_get_status_running(self, scheduler, mock_db_session):
        """Test getting status when scheduler is running."""
        # Mock empty queue list for startup
        mock_db_session.query.return_value.filter.return_value.all.return_value = []

        await scheduler.start()

        status = scheduler.get_status()

        assert status["running"] is True
        assert status["paused"] is False
        assert isinstance(status["jobs_count"], int)
        assert isinstance(status["jobs"], list)

    @pytest.mark.asyncio
    async def test_get_status_with_jobs(self, scheduler, mock_db_session):
        """Test getting status with scheduled jobs."""
        # Mock empty queue list for startup
        mock_db_session.query.return_value.filter.return_value.all.return_value = []

        await scheduler.start()

        # Schedule a job
        queue = SearchQueue(
            id=1,
            instance_id=1,
            name="Test Queue",
            strategy="missing",
            is_recurring=True,
            interval_hours=24,
            is_active=True,
            status="pending",
        )
        queue.schedule_next_run()

        mock_db_session.query.return_value.filter.return_value.first.return_value = queue

        await scheduler.schedule_queue(1)

        status = scheduler.get_status()

        assert status["jobs_count"] == 1
        assert len(status["jobs"]) == 1
        assert status["jobs"][0]["id"] == "search_queue_1"


class TestLoadExistingQueues:
    """Test loading existing queues on startup."""

    @pytest.mark.asyncio
    async def test_load_active_queues(self, scheduler, mock_db_session):
        """Test loading active queues on startup."""
        # Create mock active queues
        queue1 = SearchQueue(
            id=1,
            instance_id=1,
            name="Queue 1",
            strategy="missing",
            is_recurring=True,
            interval_hours=24,
            is_active=True,
            status="pending",
        )
        queue1.schedule_next_run()

        queue2 = SearchQueue(
            id=2,
            instance_id=1,
            name="Queue 2",
            strategy="cutoff_unmet",
            is_recurring=True,
            interval_hours=48,
            is_active=True,
            status="pending",
        )
        queue2.schedule_next_run()

        # Mock query to return active queues
        mock_db_session.query.return_value.filter.return_value.all.return_value = [queue1, queue2]
        mock_db_session.query.return_value.filter.return_value.first.side_effect = [queue1, queue2]

        await scheduler.start()

        # Verify both jobs were scheduled
        status = scheduler.get_status()
        assert status["jobs_count"] == 2

    @pytest.mark.asyncio
    async def test_skip_inactive_queues(self, scheduler, mock_db_session):
        """Test that inactive queues are not loaded."""
        # Create mock inactive queue
        queue = SearchQueue(
            id=1,
            instance_id=1,
            name="Inactive Queue",
            strategy="missing",
            is_recurring=True,
            interval_hours=24,
            is_active=False,
            status="pending",
        )

        # Mock query to return inactive queue
        mock_db_session.query.return_value.filter.return_value.all.return_value = [queue]

        await scheduler.start()

        # Verify no jobs were scheduled
        status = scheduler.get_status()
        assert status["jobs_count"] == 0
