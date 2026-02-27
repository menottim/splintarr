"""
SearchQueue model for managing automated search operations.

This module defines the SearchQueue model for tracking scheduled and recurring
searches for media items in Sonarr/Radarr.
"""

from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from splintarr.database import Base

# Search queue status
SearchStatus = Literal["pending", "in_progress", "completed", "failed", "cancelled"]

# Search strategy types
SearchStrategy = Literal["missing", "cutoff_unmet", "recent", "custom"]


class SearchQueue(Base):
    """
    SearchQueue model for automated search operations.

    Tracks scheduled and recurring searches with:
    - Search configuration and scheduling
    - Status tracking
    - Error handling
    - Next execution time calculation
    """

    __tablename__ = "search_queue"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Instance relationship
    instance_id = Column(
        Integer,
        ForeignKey("instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Instance to search on",
    )

    # Search configuration
    name = Column(
        String(100),
        nullable=False,
        comment="User-friendly name for this search",
    )
    strategy = Column(
        Enum("missing", "cutoff_unmet", "recent", "custom", name="search_strategy_enum"),
        nullable=False,
        comment="Search strategy to use",
    )
    is_recurring = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="Whether this search should repeat automatically",
    )

    # Scheduling
    interval_hours = Column(
        Integer,
        nullable=True,
        comment="Interval between searches in hours (for recurring searches)",
    )
    next_run = Column(
        DateTime,
        nullable=True,
        index=True,
        comment="Scheduled time for next execution",
    )
    last_run = Column(
        DateTime,
        nullable=True,
        comment="Last execution time",
    )

    # Status tracking
    status = Column(
        Enum(
            "pending",
            "in_progress",
            "completed",
            "failed",
            "cancelled",
            name="search_status_enum",
        ),
        default="pending",
        nullable=False,
        index=True,
        comment="Current status of the search",
    )
    is_active = Column(
        Boolean,
        default=True,
        nullable=False,
        index=True,
        comment="Whether this search is active (inactive searches won't run)",
    )

    # Results tracking
    items_found = Column(
        Integer,
        default=0,
        nullable=False,
        comment="Number of items found in last search",
    )
    items_searched = Column(
        Integer,
        default=0,
        nullable=False,
        comment="Number of items searched in last execution",
    )

    # Error handling
    error_message = Column(
        Text,
        nullable=True,
        comment="Error message from last failed execution",
    )
    consecutive_failures = Column(
        Integer,
        default=0,
        nullable=False,
        comment="Number of consecutive failed executions",
    )

    # Custom filters (JSON stored as text)
    filters = Column(
        Text,
        nullable=True,
        comment="JSON-encoded custom filter configuration",
    )

    # Timestamps
    created_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False,
        comment="Queue item creation timestamp",
    )
    updated_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="Last queue item update timestamp",
    )

    # Relationships
    instance = relationship("Instance", back_populates="search_queues")

    def __repr__(self) -> str:
        """String representation of SearchQueue."""
        return (
            f"<SearchQueue(id={self.id}, name='{self.name}', "
            f"strategy='{self.strategy}', status='{self.status}')>"
        )

    def is_ready_to_run(self) -> bool:
        """
        Check if this search is ready to be executed.

        A search is ready if:
        1. It is active
        2. Status is pending (not already running)
        3. Next run time has passed (or is None for immediate execution)

        Returns:
            bool: True if search should be executed now
        """
        if not self.is_active:
            return False

        if self.status != "pending":
            return False

        if self.next_run and datetime.utcnow() < self.next_run:
            return False

        return True

    def mark_in_progress(self) -> None:
        """Mark the search as currently in progress."""
        self.status = "in_progress"
        self.last_run = datetime.utcnow()

    def mark_completed(self, items_found: int, items_searched: int) -> None:
        """
        Mark the search as completed successfully.

        Args:
            items_found: Number of items found matching the search
            items_searched: Total number of items searched
        """
        self.status = "completed"
        self.items_found = items_found
        self.items_searched = items_searched
        self.error_message = None
        self.consecutive_failures = 0

        # Schedule next run if recurring
        if self.is_recurring and self.interval_hours:
            self.schedule_next_run()
        else:
            self.next_run = None

    def mark_failed(self, error: str) -> None:
        """
        Mark the search as failed.

        Args:
            error: Error message describing the failure
        """
        self.status = "failed"
        self.error_message = error
        self.consecutive_failures += 1

        # Deactivate after too many consecutive failures
        if self.consecutive_failures >= 5:
            self.is_active = False
            self.error_message = (
                f"Deactivated after {self.consecutive_failures} consecutive failures. "
                f"Last error: {error}"
            )
        elif self.is_recurring and self.interval_hours:
            # Still schedule next run for recurring searches
            self.schedule_next_run()

    def mark_cancelled(self) -> None:
        """Mark the search as cancelled by user."""
        self.status = "cancelled"
        self.is_active = False
        self.next_run = None

    def schedule_next_run(self, delay_hours: int | None = None) -> None:
        """
        Schedule the next execution.

        Args:
            delay_hours: Custom delay in hours (uses interval_hours if not specified)
        """
        if delay_hours is None:
            delay_hours = self.interval_hours or 24

        self.next_run = datetime.utcnow() + timedelta(hours=delay_hours)
        self.status = "pending"

    def reset_for_retry(self) -> None:
        """
        Reset the search to pending status for manual retry.

        Clears error state and schedules for immediate execution.
        """
        self.status = "pending"
        self.next_run = None
        self.error_message = None
        self.consecutive_failures = 0

    def activate(self) -> None:
        """
        Activate this search.

        Resets status and schedules next run if recurring.
        """
        self.is_active = True
        self.status = "pending"
        self.consecutive_failures = 0

        if self.is_recurring and self.interval_hours:
            self.schedule_next_run()

    def deactivate(self) -> None:
        """
        Deactivate this search.

        Prevents future automatic executions.
        """
        self.is_active = False
        self.next_run = None

    @property
    def time_until_next_run(self) -> timedelta | None:
        """
        Calculate time remaining until next execution.

        Returns:
            timedelta | None: Time remaining, or None if not scheduled
        """
        if not self.next_run:
            return None

        return self.next_run - datetime.utcnow()

    @property
    def is_overdue(self) -> bool:
        """
        Check if the scheduled execution is overdue.

        Returns:
            bool: True if next_run time has passed
        """
        if not self.next_run:
            return False

        return datetime.utcnow() > self.next_run
