"""
Search History Service for Vibe-Quality-Searcharr.

This module provides search history management and analytics:
- History record retrieval and filtering
- Statistics calculation (success rates, trends)
- History cleanup and archival
- Reporting and dashboards
- Performance metrics tracking
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import func
from sqlalchemy.orm import Session

from vibe_quality_searcharr.models import SearchHistory

logger = structlog.get_logger()


class SearchHistoryError(Exception):
    """Base exception for search history errors."""

    pass


class SearchHistoryService:
    """
    Service for managing search execution history.

    Provides:
    - History query and filtering
    - Statistical analysis
    - Cleanup operations
    - Performance tracking
    """

    def __init__(self, db_session_factory: Callable[[], Session]):
        """
        Initialize search history service.

        Args:
            db_session_factory: Factory function to create database sessions
        """
        self.db_session_factory = db_session_factory
        logger.info("search_history_service_initialized")

    def get_history(
        self,
        instance_id: int | None = None,
        queue_id: int | None = None,
        strategy: str | None = None,
        status: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SearchHistory]:
        """
        Get search history with optional filtering.

        Args:
            instance_id: Filter by instance ID
            queue_id: Filter by queue ID
            strategy: Filter by strategy
            status: Filter by status
            start_date: Filter by start date (>=)
            end_date: Filter by end date (<=)
            limit: Maximum number of records (default: 100, max: 1000)
            offset: Offset for pagination (default: 0)

        Returns:
            list[SearchHistory]: List of history records
        """
        db = self.db_session_factory()

        try:
            query = db.query(SearchHistory)

            # Apply filters
            if instance_id is not None:
                query = query.filter(SearchHistory.instance_id == instance_id)

            if queue_id is not None:
                query = query.filter(SearchHistory.search_queue_id == queue_id)

            if strategy is not None:
                query = query.filter(SearchHistory.strategy == strategy)

            if status is not None:
                query = query.filter(SearchHistory.status == status)

            if start_date is not None:
                query = query.filter(SearchHistory.started_at >= start_date)

            if end_date is not None:
                query = query.filter(SearchHistory.started_at <= end_date)

            # Order by most recent first
            query = query.order_by(SearchHistory.started_at.desc())

            # Apply pagination
            query = query.limit(min(limit, 1000)).offset(offset)

            return query.all()

        finally:
            db.close()

    def get_history_count(
        self,
        instance_id: int | None = None,
        queue_id: int | None = None,
        strategy: str | None = None,
        status: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> int:
        """
        Get total count of history records matching filters.

        Args:
            instance_id: Filter by instance ID
            queue_id: Filter by queue ID
            strategy: Filter by strategy
            status: Filter by status
            start_date: Filter by start date (>=)
            end_date: Filter by end date (<=)

        Returns:
            int: Total count of matching records
        """
        db = self.db_session_factory()

        try:
            query = db.query(func.count(SearchHistory.id))

            # Apply filters
            if instance_id is not None:
                query = query.filter(SearchHistory.instance_id == instance_id)

            if queue_id is not None:
                query = query.filter(SearchHistory.search_queue_id == queue_id)

            if strategy is not None:
                query = query.filter(SearchHistory.strategy == strategy)

            if status is not None:
                query = query.filter(SearchHistory.status == status)

            if start_date is not None:
                query = query.filter(SearchHistory.started_at >= start_date)

            if end_date is not None:
                query = query.filter(SearchHistory.started_at <= end_date)

            return query.scalar() or 0

        finally:
            db.close()

    def get_statistics(
        self,
        instance_id: int | None = None,
        queue_id: int | None = None,
        days: int = 30,
    ) -> dict[str, Any]:
        """
        Get search statistics for the specified period.

        Args:
            instance_id: Filter by instance ID
            queue_id: Filter by queue ID
            days: Number of days to analyze (default: 30)

        Returns:
            dict: Statistics including:
                - total_searches: int
                - successful_searches: int
                - failed_searches: int
                - success_rate: float (0.0 to 1.0)
                - total_items_searched: int
                - total_items_found: int
                - total_searches_triggered: int
                - avg_duration_seconds: float
                - searches_by_strategy: dict[str, int]
                - searches_by_day: list[dict]
        """
        db = self.db_session_factory()

        try:
            # Calculate date range
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=days)

            # Base query with date filter
            base_query = db.query(SearchHistory).filter(
                SearchHistory.started_at >= start_date,
                SearchHistory.started_at <= end_date,
            )

            if instance_id is not None:
                base_query = base_query.filter(SearchHistory.instance_id == instance_id)

            if queue_id is not None:
                base_query = base_query.filter(SearchHistory.search_queue_id == queue_id)

            # Get all records for analysis
            records = base_query.all()

            # Calculate statistics
            total_searches = len(records)
            successful_searches = sum(1 for r in records if r.was_successful)
            failed_searches = sum(1 for r in records if r.status == "failed")
            success_rate = successful_searches / total_searches if total_searches > 0 else 0.0

            total_items_searched = sum(r.items_searched for r in records)
            total_items_found = sum(r.items_found for r in records)
            total_searches_triggered = sum(r.searches_triggered for r in records)

            # Average duration
            durations = [r.duration_seconds for r in records if r.duration_seconds is not None]
            avg_duration_seconds = sum(durations) / len(durations) if durations else 0.0

            # Searches by strategy
            searches_by_strategy: dict[str, int] = {}
            for record in records:
                strategy = record.strategy
                searches_by_strategy[strategy] = searches_by_strategy.get(strategy, 0) + 1

            # Searches by day
            searches_by_day = []
            for day_offset in range(days):
                day = start_date + timedelta(days=day_offset)
                day_end = day + timedelta(days=1)

                day_records = [r for r in records if day <= r.started_at < day_end]

                searches_by_day.append(
                    {
                        "date": day.date().isoformat(),
                        "count": len(day_records),
                        "successful": sum(1 for r in day_records if r.was_successful),
                        "failed": sum(1 for r in day_records if r.status == "failed"),
                    }
                )

            return {
                "total_searches": total_searches,
                "successful_searches": successful_searches,
                "failed_searches": failed_searches,
                "success_rate": success_rate,
                "total_items_searched": total_items_searched,
                "total_items_found": total_items_found,
                "total_searches_triggered": total_searches_triggered,
                "avg_duration_seconds": avg_duration_seconds,
                "searches_by_strategy": searches_by_strategy,
                "searches_by_day": searches_by_day,
            }

        finally:
            db.close()

    def cleanup_old_history(self, days: int = 90) -> int:
        """
        Delete history records older than specified days.

        Args:
            days: Number of days to keep (default: 90)

        Returns:
            int: Number of records deleted

        Raises:
            SearchHistoryError: If cleanup fails
        """
        db = self.db_session_factory()

        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)

            # Count records to delete
            count = db.query(SearchHistory).filter(SearchHistory.started_at < cutoff_date).count()

            # Delete old records
            db.query(SearchHistory).filter(SearchHistory.started_at < cutoff_date).delete()

            db.commit()

            logger.info("history_cleanup_completed", deleted_count=count, days=days)

            return count

        except Exception as e:
            db.rollback()
            logger.error("history_cleanup_failed", error=str(e))
            raise SearchHistoryError(f"Failed to cleanup history: {e}") from e

        finally:
            db.close()

    def get_recent_failures(
        self,
        instance_id: int | None = None,
        limit: int = 10,
    ) -> list[SearchHistory]:
        """
        Get recent failed searches for troubleshooting.

        Args:
            instance_id: Filter by instance ID
            limit: Maximum number of records (default: 10)

        Returns:
            list[SearchHistory]: Recent failed searches
        """
        db = self.db_session_factory()

        try:
            query = db.query(SearchHistory).filter(SearchHistory.status == "failed")

            if instance_id is not None:
                query = query.filter(SearchHistory.instance_id == instance_id)

            query = query.order_by(SearchHistory.started_at.desc()).limit(limit)

            return query.all()

        finally:
            db.close()

    def get_queue_performance(self, queue_id: int, days: int = 30) -> dict[str, Any]:
        """
        Get performance metrics for a specific queue.

        Args:
            queue_id: Queue ID
            days: Number of days to analyze (default: 30)

        Returns:
            dict: Performance metrics including:
                - total_executions: int
                - success_rate: float
                - avg_items_found: float
                - avg_duration: float
                - last_success: datetime | None
                - last_failure: datetime | None
        """
        db = self.db_session_factory()

        try:
            start_date = datetime.utcnow() - timedelta(days=days)

            records = (
                db.query(SearchHistory)
                .filter(
                    SearchHistory.search_queue_id == queue_id,
                    SearchHistory.started_at >= start_date,
                )
                .all()
            )

            if not records:
                return {
                    "total_executions": 0,
                    "success_rate": 0.0,
                    "avg_items_found": 0.0,
                    "avg_duration": 0.0,
                    "last_success": None,
                    "last_failure": None,
                }

            total_executions = len(records)
            successful = sum(1 for r in records if r.was_successful)
            success_rate = successful / total_executions

            avg_items_found = sum(r.items_found for r in records) / total_executions

            durations = [r.duration_seconds for r in records if r.duration_seconds is not None]
            avg_duration = sum(durations) / len(durations) if durations else 0.0

            # Find last success and failure
            successful_records = [r for r in records if r.was_successful]
            failed_records = [r for r in records if r.status == "failed"]

            last_success = max((r.started_at for r in successful_records), default=None)
            last_failure = max((r.started_at for r in failed_records), default=None)

            return {
                "total_executions": total_executions,
                "success_rate": success_rate,
                "avg_items_found": avg_items_found,
                "avg_duration": avg_duration,
                "last_success": last_success,
                "last_failure": last_failure,
            }

        finally:
            db.close()


# Global service instance (singleton)
_history_service_instance: SearchHistoryService | None = None


def get_history_service(db_session_factory: Callable[[], Session]) -> SearchHistoryService:
    """
    Get or create the global search history service instance.

    Args:
        db_session_factory: Factory function to create database sessions

    Returns:
        SearchHistoryService: Global service instance
    """
    global _history_service_instance

    if _history_service_instance is None:
        _history_service_instance = SearchHistoryService(db_session_factory)

    return _history_service_instance
