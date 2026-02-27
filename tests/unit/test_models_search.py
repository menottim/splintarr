"""
Unit tests for SearchQueue and SearchHistory models.

Tests search queue scheduling, status tracking, and search history audit trail.
"""

from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from splintarr.models.instance import Instance
from splintarr.models.search_history import SearchHistory
from splintarr.models.search_queue import SearchQueue
from splintarr.models.user import User


class TestSearchQueueModel:
    """Test SearchQueue model functionality."""

    def test_create_search_queue_basic(self, db_session):
        """Test creating a basic search queue item."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(
            instance_id=instance.id, name="Find Missing Episodes", strategy="missing"
        )
        db_session.add(search_queue)
        db_session.commit()

        assert search_queue.id is not None
        assert search_queue.name == "Find Missing Episodes"
        assert search_queue.strategy == "missing"

    def test_search_queue_default_values(self, db_session):
        """Test that search queue has correct default values."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(instance_id=instance.id, name="Test", strategy="missing")
        db_session.add(search_queue)
        db_session.commit()

        assert search_queue.is_recurring is False
        assert search_queue.status == "pending"
        assert search_queue.is_active is True
        assert search_queue.items_found == 0
        assert search_queue.items_searched == 0
        assert search_queue.consecutive_failures == 0

    def test_search_queue_timestamps_auto_set(self, db_session):
        """Test that timestamps are set automatically."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(instance_id=instance.id, name="Test", strategy="missing")
        db_session.add(search_queue)
        db_session.commit()

        assert search_queue.created_at is not None
        assert search_queue.updated_at is not None

    def test_search_queue_strategies(self, db_session):
        """Test different search strategies."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        strategies = ["missing", "cutoff_unmet", "recent", "custom"]

        for strategy in strategies:
            search = SearchQueue(
                instance_id=instance.id, name=f"Test {strategy}", strategy=strategy
            )
            db_session.add(search)

        db_session.commit()

        # Verify all strategies were created
        for strategy in strategies:
            result = db_session.query(SearchQueue).filter_by(strategy=strategy).first()
            assert result is not None

    def test_search_queue_recurring_configuration(self, db_session):
        """Test recurring search configuration."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(
            instance_id=instance.id,
            name="Daily Search",
            strategy="missing",
            is_recurring=True,
            interval_hours=24,
        )
        db_session.add(search_queue)
        db_session.commit()

        assert search_queue.is_recurring is True
        assert search_queue.interval_hours == 24

    def test_search_queue_repr(self, db_session):
        """Test search queue string representation."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(instance_id=instance.id, name="Test Search", strategy="missing")
        db_session.add(search_queue)
        db_session.commit()

        repr_str = repr(search_queue)
        assert "Test Search" in repr_str
        assert "missing" in repr_str
        assert "pending" in repr_str


class TestSearchQueueIsReadyToRun:
    """Test SearchQueue.is_ready_to_run() method."""

    def test_is_ready_to_run_when_conditions_met(self, db_session):
        """Test is_ready_to_run returns True when all conditions met."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(
            instance_id=instance.id, name="Test", strategy="missing", is_active=True, status="pending"
        )
        db_session.add(search_queue)
        db_session.commit()

        assert search_queue.is_ready_to_run() is True

    def test_is_ready_to_run_not_active(self, db_session):
        """Test is_ready_to_run returns False when not active."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(
            instance_id=instance.id,
            name="Test",
            strategy="missing",
            is_active=False,
            status="pending",
        )
        db_session.add(search_queue)
        db_session.commit()

        assert search_queue.is_ready_to_run() is False

    def test_is_ready_to_run_wrong_status(self, db_session):
        """Test is_ready_to_run returns False when status is not pending."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(
            instance_id=instance.id,
            name="Test",
            strategy="missing",
            is_active=True,
            status="in_progress",
        )
        db_session.add(search_queue)
        db_session.commit()

        assert search_queue.is_ready_to_run() is False

    def test_is_ready_to_run_future_next_run(self, db_session):
        """Test is_ready_to_run returns False when next_run is in future."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(
            instance_id=instance.id,
            name="Test",
            strategy="missing",
            is_active=True,
            status="pending",
            next_run=datetime.utcnow() + timedelta(hours=1),
        )
        db_session.add(search_queue)
        db_session.commit()

        assert search_queue.is_ready_to_run() is False

    def test_is_ready_to_run_past_next_run(self, db_session):
        """Test is_ready_to_run returns True when next_run is in past."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(
            instance_id=instance.id,
            name="Test",
            strategy="missing",
            is_active=True,
            status="pending",
            next_run=datetime.utcnow() - timedelta(hours=1),
        )
        db_session.add(search_queue)
        db_session.commit()

        assert search_queue.is_ready_to_run() is True


class TestSearchQueueStatusManagement:
    """Test SearchQueue status management methods."""

    def test_mark_in_progress(self, db_session):
        """Test marking search as in progress."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(instance_id=instance.id, name="Test", strategy="missing")
        db_session.add(search_queue)
        db_session.commit()

        search_queue.mark_in_progress()

        assert search_queue.status == "in_progress"
        assert search_queue.last_run is not None

    def test_mark_completed_success(self, db_session):
        """Test marking search as completed successfully."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(instance_id=instance.id, name="Test", strategy="missing")
        search_queue.consecutive_failures = 2
        db_session.add(search_queue)
        db_session.commit()

        search_queue.mark_completed(items_found=10, items_searched=50)

        assert search_queue.status == "completed"
        assert search_queue.items_found == 10
        assert search_queue.items_searched == 50
        assert search_queue.error_message is None
        assert search_queue.consecutive_failures == 0

    def test_mark_completed_schedules_next_run_for_recurring(self, db_session):
        """Test that completing recurring search schedules next run."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(
            instance_id=instance.id,
            name="Test",
            strategy="missing",
            is_recurring=True,
            interval_hours=24,
        )
        db_session.add(search_queue)
        db_session.commit()

        search_queue.mark_completed(items_found=10, items_searched=50)

        assert search_queue.next_run is not None
        assert search_queue.status == "pending"

    def test_mark_completed_no_next_run_for_one_time(self, db_session):
        """Test that completing one-time search doesn't schedule next run."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(
            instance_id=instance.id, name="Test", strategy="missing", is_recurring=False
        )
        db_session.add(search_queue)
        db_session.commit()

        search_queue.mark_completed(items_found=10, items_searched=50)

        assert search_queue.next_run is None

    def test_mark_failed(self, db_session):
        """Test marking search as failed."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(instance_id=instance.id, name="Test", strategy="missing")
        db_session.add(search_queue)
        db_session.commit()

        error_message = "Connection timeout"
        search_queue.mark_failed(error_message)

        assert search_queue.status == "failed"
        assert search_queue.error_message == error_message
        assert search_queue.consecutive_failures == 1

    def test_mark_failed_deactivates_after_max_failures(self, db_session):
        """Test that search is deactivated after too many failures."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(
            instance_id=instance.id,
            name="Test",
            strategy="missing",
            is_recurring=True,
            interval_hours=24,
        )
        db_session.add(search_queue)
        db_session.commit()

        # Fail 5 times
        for i in range(5):
            search_queue.mark_failed(f"Error {i}")

        assert search_queue.consecutive_failures == 5
        assert search_queue.is_active is False

    def test_mark_cancelled(self, db_session):
        """Test marking search as cancelled."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(instance_id=instance.id, name="Test", strategy="missing")
        db_session.add(search_queue)
        db_session.commit()

        search_queue.mark_cancelled()

        assert search_queue.status == "cancelled"
        assert search_queue.is_active is False
        assert search_queue.next_run is None


class TestSearchQueueScheduling:
    """Test SearchQueue scheduling methods."""

    def test_schedule_next_run_default_interval(self, db_session):
        """Test scheduling next run with default interval."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(
            instance_id=instance.id, name="Test", strategy="missing", interval_hours=24
        )
        db_session.add(search_queue)
        db_session.commit()

        search_queue.schedule_next_run()

        assert search_queue.next_run is not None
        assert search_queue.status == "pending"

    def test_schedule_next_run_custom_delay(self, db_session):
        """Test scheduling next run with custom delay."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(instance_id=instance.id, name="Test", strategy="missing")
        db_session.add(search_queue)
        db_session.commit()

        search_queue.schedule_next_run(delay_hours=12)

        expected_time = datetime.utcnow() + timedelta(hours=12)
        time_diff = abs((search_queue.next_run - expected_time).total_seconds())

        # Allow 1 second tolerance
        assert time_diff < 1

    def test_reset_for_retry(self, db_session):
        """Test resetting search for retry."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(
            instance_id=instance.id,
            name="Test",
            strategy="missing",
            status="failed",
            error_message="Previous error",
            consecutive_failures=3,
        )
        db_session.add(search_queue)
        db_session.commit()

        search_queue.reset_for_retry()

        assert search_queue.status == "pending"
        assert search_queue.next_run is None
        assert search_queue.error_message is None
        assert search_queue.consecutive_failures == 0

    def test_activate(self, db_session):
        """Test activating a search."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(
            instance_id=instance.id,
            name="Test",
            strategy="missing",
            is_active=False,
            is_recurring=True,
            interval_hours=24,
        )
        db_session.add(search_queue)
        db_session.commit()

        search_queue.activate()

        assert search_queue.is_active is True
        assert search_queue.status == "pending"
        assert search_queue.consecutive_failures == 0
        assert search_queue.next_run is not None

    def test_deactivate(self, db_session):
        """Test deactivating a search."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(
            instance_id=instance.id,
            name="Test",
            strategy="missing",
            is_active=True,
            next_run=datetime.utcnow() + timedelta(hours=1),
        )
        db_session.add(search_queue)
        db_session.commit()

        search_queue.deactivate()

        assert search_queue.is_active is False
        assert search_queue.next_run is None


class TestSearchQueueProperties:
    """Test SearchQueue computed properties."""

    def test_time_until_next_run_positive(self, db_session):
        """Test time_until_next_run with future next_run."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(
            instance_id=instance.id,
            name="Test",
            strategy="missing",
            next_run=datetime.utcnow() + timedelta(hours=2),
        )
        db_session.add(search_queue)
        db_session.commit()

        time_until = search_queue.time_until_next_run

        assert time_until is not None
        assert time_until.total_seconds() > 0

    def test_time_until_next_run_none(self, db_session):
        """Test time_until_next_run when next_run is None."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(instance_id=instance.id, name="Test", strategy="missing")
        db_session.add(search_queue)
        db_session.commit()

        assert search_queue.time_until_next_run is None

    def test_is_overdue_false(self, db_session):
        """Test is_overdue with future next_run."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(
            instance_id=instance.id,
            name="Test",
            strategy="missing",
            next_run=datetime.utcnow() + timedelta(hours=1),
        )
        db_session.add(search_queue)
        db_session.commit()

        assert search_queue.is_overdue is False

    def test_is_overdue_true(self, db_session):
        """Test is_overdue with past next_run."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(
            instance_id=instance.id,
            name="Test",
            strategy="missing",
            next_run=datetime.utcnow() - timedelta(hours=1),
        )
        db_session.add(search_queue)
        db_session.commit()

        assert search_queue.is_overdue is True


class TestSearchHistoryModel:
    """Test SearchHistory model functionality."""

    def test_create_search_history(self, db_session):
        """Test creating a search history record."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        history = SearchHistory(
            instance_id=instance.id,
            search_name="Test Search",
            strategy="missing",
            started_at=datetime.utcnow(),
            status="success",
        )
        db_session.add(history)
        db_session.commit()

        assert history.id is not None
        assert history.search_name == "Test Search"
        assert history.strategy == "missing"

    def test_search_history_factory_method(self, db_session):
        """Test creating history using factory method."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        history = SearchHistory.create_for_search(
            instance_id=instance.id,
            search_queue_id=None,
            search_name="Manual Search",
            strategy="missing",
        )
        db_session.add(history)
        db_session.commit()

        assert history.id is not None
        assert history.search_name == "Manual Search"
        assert history.started_at is not None

    def test_search_history_mark_completed(self, db_session):
        """Test marking history as completed."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        history = SearchHistory.create_for_search(
            instance_id=instance.id,
            search_queue_id=None,
            search_name="Test",
            strategy="missing",
        )
        db_session.add(history)
        db_session.commit()

        history.mark_completed(
            status="success",
            items_searched=100,
            items_found=25,
            searches_triggered=25,
            errors_encountered=0,
        )

        assert history.status == "success"
        assert history.items_searched == 100
        assert history.items_found == 25
        assert history.searches_triggered == 25
        assert history.completed_at is not None
        assert history.duration_seconds is not None

    def test_search_history_mark_failed(self, db_session):
        """Test marking history as failed."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        history = SearchHistory.create_for_search(
            instance_id=instance.id,
            search_queue_id=None,
            search_name="Test",
            strategy="missing",
        )
        db_session.add(history)
        db_session.commit()

        error_message = "API connection failed"
        history.mark_failed(error_message)

        assert history.status == "failed"
        assert history.error_message == error_message
        assert history.completed_at is not None

    def test_search_history_properties(self, db_session):
        """Test SearchHistory computed properties."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        history = SearchHistory.create_for_search(
            instance_id=instance.id,
            search_queue_id=None,
            search_name="Test",
            strategy="missing",
        )
        db_session.add(history)
        db_session.commit()

        # Before completion
        assert history.is_completed is False

        history.mark_completed(
            status="success", items_searched=100, items_found=25, searches_triggered=25
        )

        # After completion
        assert history.is_completed is True
        assert history.was_successful is True
        assert history.success_rate == 0.25

    def test_search_history_repr(self, db_session):
        """Test search history string representation."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        history = SearchHistory.create_for_search(
            instance_id=instance.id,
            search_queue_id=None,
            search_name="Test Search",
            strategy="missing",
        )
        db_session.add(history)
        db_session.commit()

        repr_str = repr(history)
        assert "Test Search" in repr_str
        assert "success" in repr_str  # default status from factory
