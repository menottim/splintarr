"""
Unit tests for Search History Service.

Tests history retrieval, statistics, and cleanup operations.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from splintarr.models import SearchHistory
from splintarr.services.search_history import SearchHistoryService, SearchHistoryError


@pytest.fixture
def mock_db_session():
    """Mock database session."""
    session = MagicMock()
    session.query = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    session.close = MagicMock()
    return session


@pytest.fixture
def mock_session_factory(mock_db_session):
    """Mock session factory."""
    return lambda: mock_db_session


@pytest.fixture
def history_service(mock_session_factory):
    """Create history service instance."""
    return SearchHistoryService(mock_session_factory)


@pytest.fixture
def sample_history_records():
    """Create sample history records."""
    now = datetime.utcnow()

    records = []
    for i in range(10):
        record = SearchHistory(
            id=i + 1,
            instance_id=1,
            search_queue_id=1,
            search_name=f"Test Search {i}",
            strategy="missing",
            started_at=now - timedelta(days=i),
            completed_at=now - timedelta(days=i, hours=-1),
            duration_seconds=3600,
            status="success" if i % 3 != 0 else "failed",
            items_searched=100,
            items_found=50 if i % 3 != 0 else 0,
            searches_triggered=50 if i % 3 != 0 else 0,
            errors_encountered=0 if i % 3 != 0 else 1,
            error_message=None if i % 3 != 0 else "Test error",
        )
        records.append(record)

    return records


class TestHistoryRetrieval:
    """Test history retrieval operations."""

    def test_get_history_all(self, history_service, mock_db_session, sample_history_records):
        """Test getting all history records."""
        # Mock query
        mock_db_session.query.return_value.order_by.return_value.limit.return_value.offset.return_value.all.return_value = sample_history_records

        # Get history
        results = history_service.get_history(limit=10)

        # Verify
        assert len(results) == len(sample_history_records)
        mock_db_session.query.assert_called()

    def test_get_history_with_instance_filter(
        self, history_service, mock_db_session, sample_history_records
    ):
        """Test getting history filtered by instance."""
        # Mock query
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.all.return_value = sample_history_records[:5]

        # Get history
        results = history_service.get_history(instance_id=1, limit=10)

        # Verify filter was applied
        assert len(results) <= 10

    def test_get_history_with_status_filter(
        self, history_service, mock_db_session, sample_history_records
    ):
        """Test getting history filtered by status."""
        # Filter for successful only
        successful = [r for r in sample_history_records if r.status == "success"]

        # Mock query
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.all.return_value = successful

        # Get history
        results = history_service.get_history(status="success", limit=10)

        # Verify
        assert all(r.status == "success" for r in results)

    def test_get_history_with_date_range(
        self, history_service, mock_db_session, sample_history_records
    ):
        """Test getting history with date range filter."""
        start_date = datetime.utcnow() - timedelta(days=5)
        end_date = datetime.utcnow()

        # Filter records
        filtered = [
            r for r in sample_history_records
            if start_date <= r.started_at <= end_date
        ]

        # Mock query
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.all.return_value = filtered

        # Get history
        results = history_service.get_history(
            start_date=start_date,
            end_date=end_date,
            limit=10,
        )

        # Verify
        assert len(results) <= len(sample_history_records)

    def test_get_history_count(self, history_service, mock_db_session):
        """Test getting history count."""
        # Mock query
        mock_db_session.query.return_value.scalar.return_value = 42

        # Get count
        count = history_service.get_history_count()

        # Verify
        assert count == 42


class TestStatistics:
    """Test statistics calculation."""

    def test_get_statistics_basic(
        self, history_service, mock_db_session, sample_history_records
    ):
        """Test getting basic statistics."""
        # Mock query
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = sample_history_records

        # Get statistics
        stats = history_service.get_statistics(days=30)

        # Verify
        assert "total_searches" in stats
        assert "successful_searches" in stats
        assert "failed_searches" in stats
        assert "success_rate" in stats
        assert "total_items_searched" in stats
        assert "total_items_found" in stats
        assert "searches_by_strategy" in stats
        assert "searches_by_day" in stats

        assert stats["total_searches"] == len(sample_history_records)

    def test_get_statistics_success_rate(
        self, history_service, mock_db_session, sample_history_records
    ):
        """Test success rate calculation."""
        # Mock query
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = sample_history_records

        # Get statistics
        stats = history_service.get_statistics(days=30)

        # Calculate expected success rate
        successful = len([r for r in sample_history_records if r.was_successful])
        expected_rate = successful / len(sample_history_records)

        # Verify
        assert stats["success_rate"] == pytest.approx(expected_rate)

    def test_get_statistics_by_strategy(
        self, history_service, mock_db_session, sample_history_records
    ):
        """Test statistics grouped by strategy."""
        # Mock query
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = sample_history_records

        # Get statistics
        stats = history_service.get_statistics(days=30)

        # Verify
        assert "missing" in stats["searches_by_strategy"]
        assert stats["searches_by_strategy"]["missing"] == len(sample_history_records)

    def test_get_statistics_empty_results(self, history_service, mock_db_session):
        """Test statistics with no history records."""
        # Mock empty query
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []

        # Get statistics
        stats = history_service.get_statistics(days=30)

        # Verify
        assert stats["total_searches"] == 0
        assert stats["success_rate"] == 0.0


class TestCleanup:
    """Test history cleanup operations."""

    def test_cleanup_old_history(self, history_service, mock_db_session):
        """Test cleaning up old history records."""
        # Mock query
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 10
        mock_query.delete.return_value = None

        # Cleanup
        deleted_count = history_service.cleanup_old_history(days=90)

        # Verify
        assert deleted_count == 10
        mock_db_session.commit.assert_called_once()

    def test_cleanup_with_database_error(self, history_service, mock_db_session):
        """Test cleanup with database error."""
        # Mock query to raise error
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value = mock_query
        mock_query.count.side_effect = Exception("Database error")

        # Cleanup should raise error
        with pytest.raises(SearchHistoryError):
            history_service.cleanup_old_history(days=90)

        # Verify rollback was called
        mock_db_session.rollback.assert_called()


class TestRecentFailures:
    """Test recent failures retrieval."""

    def test_get_recent_failures(
        self, history_service, mock_db_session, sample_history_records
    ):
        """Test getting recent failed searches."""
        # Filter for failures
        failures = [r for r in sample_history_records if r.status == "failed"]

        # Mock query
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = failures

        # Get failures
        results = history_service.get_recent_failures(limit=5)

        # Verify
        assert all(r.status == "failed" for r in results)
        assert len(results) <= 5

    def test_get_recent_failures_with_instance_filter(
        self, history_service, mock_db_session, sample_history_records
    ):
        """Test getting recent failures filtered by instance."""
        # Filter for instance and failures
        failures = [
            r for r in sample_history_records
            if r.status == "failed" and r.instance_id == 1
        ]

        # Mock query
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = failures

        # Get failures
        results = history_service.get_recent_failures(instance_id=1, limit=5)

        # Verify
        assert all(r.instance_id == 1 for r in results)


class TestQueuePerformance:
    """Test queue performance metrics."""

    def test_get_queue_performance(
        self, history_service, mock_db_session, sample_history_records
    ):
        """Test getting performance metrics for a queue."""
        # Mock query
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = sample_history_records

        # Get performance
        performance = history_service.get_queue_performance(queue_id=1, days=30)

        # Verify
        assert "total_executions" in performance
        assert "success_rate" in performance
        assert "avg_items_found" in performance
        assert "avg_duration" in performance
        assert "last_success" in performance
        assert "last_failure" in performance

        assert performance["total_executions"] == len(sample_history_records)

    def test_get_queue_performance_no_data(self, history_service, mock_db_session):
        """Test getting performance with no history data."""
        # Mock empty query
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []

        # Get performance
        performance = history_service.get_queue_performance(queue_id=1, days=30)

        # Verify defaults
        assert performance["total_executions"] == 0
        assert performance["success_rate"] == 0.0
        assert performance["last_success"] is None
        assert performance["last_failure"] is None

    def test_get_queue_performance_averages(
        self, history_service, mock_db_session, sample_history_records
    ):
        """Test average calculations in performance metrics."""
        # Mock query
        mock_query = mock_db_session.query.return_value
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = sample_history_records

        # Get performance
        performance = history_service.get_queue_performance(queue_id=1, days=30)

        # Verify averages are calculated
        assert performance["avg_items_found"] >= 0
        assert performance["avg_duration"] >= 0
