"""
SearchHistory model for tracking search execution history.

This module defines the SearchHistory model for audit trail and analytics
of all search operations performed.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Literal

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from vibe_quality_searcharr.database import Base

if TYPE_CHECKING:
    pass

# Search execution status
SearchExecutionStatus = Literal["success", "partial_success", "failed"]

# Search strategy types
SearchStrategy = Literal["missing", "cutoff_unmet", "recent", "custom"]


class SearchHistory(Base):
    """
    SearchHistory model for tracking search execution history.

    Provides an audit trail and analytics for:
    - Search execution results
    - Performance metrics
    - Error tracking
    - Success rates over time
    """

    __tablename__ = "search_history"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Instance relationship
    instance_id = Column(
        Integer,
        ForeignKey("instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Instance where search was executed",
    )

    # Search identification
    search_queue_id = Column(
        Integer,
        nullable=True,
        index=True,
        comment="Reference to SearchQueue item (NULL for manual searches)",
    )
    search_name = Column(
        String(100),
        nullable=False,
        comment="Name of the search that was executed",
    )
    strategy = Column(
        Enum("missing", "cutoff_unmet", "recent", "custom", name="search_strategy_enum"),
        nullable=False,
        index=True,
        comment="Search strategy that was used",
    )

    # Execution details
    started_at = Column(
        DateTime,
        nullable=False,
        index=True,
        comment="When the search execution started",
    )
    completed_at = Column(
        DateTime,
        nullable=True,
        comment="When the search execution completed (NULL if still running)",
    )
    duration_seconds = Column(
        Integer,
        nullable=True,
        comment="Total execution time in seconds",
    )

    # Status and results
    status = Column(
        Enum("success", "partial_success", "failed", name="search_execution_status_enum"),
        nullable=False,
        index=True,
        comment="Execution status",
    )
    items_searched = Column(
        Integer,
        default=0,
        nullable=False,
        comment="Total number of items searched",
    )
    items_found = Column(
        Integer,
        default=0,
        nullable=False,
        comment="Number of items that matched search criteria",
    )
    searches_triggered = Column(
        Integer,
        default=0,
        nullable=False,
        comment="Number of searches triggered in Sonarr/Radarr",
    )

    # Error tracking
    error_message = Column(
        Text,
        nullable=True,
        comment="Error message if search failed",
    )
    errors_encountered = Column(
        Integer,
        default=0,
        nullable=False,
        comment="Number of errors encountered during execution",
    )

    # Additional metadata (JSON stored as text)
    search_metadata = Column(
        Text,
        nullable=True,
        comment="JSON-encoded additional metadata (filters, API responses, etc.)",
    )

    # Timestamps
    created_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False,
        comment="History record creation timestamp",
    )

    # Relationships
    instance = relationship("Instance", back_populates="search_history")

    def __repr__(self) -> str:
        """String representation of SearchHistory."""
        return (
            f"<SearchHistory(id={self.id}, search_name='{self.search_name}', "
            f"status='{self.status}', items_found={self.items_found})>"
        )

    @property
    def is_completed(self) -> bool:
        """
        Check if the search execution has completed.

        Returns:
            bool: True if execution completed (success or failure)
        """
        return self.completed_at is not None

    @property
    def was_successful(self) -> bool:
        """
        Check if the search was successful.

        Returns:
            bool: True if status is success or partial_success
        """
        return self.status in ("success", "partial_success")

    @property
    def success_rate(self) -> float:
        """
        Calculate success rate as percentage of items found vs searched.

        Returns:
            float: Success rate (0.0 to 1.0)
        """
        if self.items_searched == 0:
            return 0.0

        return self.items_found / self.items_searched

    def mark_started(self) -> None:
        """Mark the search as started."""
        self.started_at = datetime.utcnow()

    def mark_completed(
        self,
        status: SearchExecutionStatus,
        items_searched: int,
        items_found: int,
        searches_triggered: int,
        errors_encountered: int = 0,
        error_message: str | None = None,
    ) -> None:
        """
        Mark the search as completed with results.

        Args:
            status: Final execution status
            items_searched: Number of items that were searched
            items_found: Number of items that matched criteria
            searches_triggered: Number of searches triggered in the instance
            errors_encountered: Number of errors during execution (default: 0)
            error_message: Error message if failed (optional)
        """
        self.completed_at = datetime.utcnow()
        self.status = status
        self.items_searched = items_searched
        self.items_found = items_found
        self.searches_triggered = searches_triggered
        self.errors_encountered = errors_encountered
        self.error_message = error_message

        # Calculate duration
        if self.started_at:
            delta = self.completed_at - self.started_at
            self.duration_seconds = int(delta.total_seconds())

    def mark_failed(self, error: str) -> None:
        """
        Mark the search as failed with an error message.

        Args:
            error: Error message describing the failure
        """
        self.completed_at = datetime.utcnow()
        self.status = "failed"
        self.error_message = error
        self.errors_encountered += 1

        # Calculate duration
        if self.started_at:
            delta = self.completed_at - self.started_at
            self.duration_seconds = int(delta.total_seconds())

    @staticmethod
    def create_for_search(
        instance_id: int,
        search_queue_id: int | None,
        search_name: str,
        strategy: SearchStrategy,
    ) -> "SearchHistory":
        """
        Factory method to create a new search history record.

        Args:
            instance_id: ID of the instance
            search_queue_id: ID of the search queue item (None for manual searches)
            search_name: Name of the search
            strategy: Search strategy being used

        Returns:
            SearchHistory: New history record (not yet added to session)
        """
        return SearchHistory(
            instance_id=instance_id,
            search_queue_id=search_queue_id,
            search_name=search_name,
            strategy=strategy,
            started_at=datetime.utcnow(),
            status="success",  # Will be updated when completed
            items_searched=0,
            items_found=0,
            searches_triggered=0,
            errors_encountered=0,
        )
