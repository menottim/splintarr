"""
SearchExclusion model for content exclusion lists.

This module defines the SearchExclusion model for allowing users to exclude
specific series or movies from automated search operations.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from splintarr.database import Base


class SearchExclusion(Base):
    """
    SearchExclusion model for content exclusion lists.

    Allows users to exclude specific content from automated searches:
    - Permanent or time-limited exclusions
    - Per-instance, per-content-item granularity
    - Optional reason for audit trail
    - Automatic expiry support
    """

    __tablename__ = "search_exclusions"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # User relationship
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="User who created this exclusion",
    )

    # Instance relationship
    instance_id = Column(
        Integer,
        ForeignKey("instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Instance this exclusion applies to",
    )

    # Content identification
    library_item_id = Column(
        Integer,
        nullable=True,
        comment="Optional reference to local LibraryItem row (may be NULL if item not synced)",
    )
    external_id = Column(
        Integer,
        nullable=False,
        index=True,
        comment="ID in the source instance (series.id or movie.id)",
    )
    content_type = Column(
        Enum("series", "movie", name="exclusion_content_type_enum"),
        nullable=False,
        comment="Type of content (series for Sonarr, movie for Radarr)",
    )
    title = Column(
        String(500),
        nullable=False,
        comment="Title of the excluded content (for display purposes)",
    )

    # Exclusion details
    reason = Column(
        Text,
        nullable=True,
        comment="Optional reason for exclusion (user-provided)",
    )
    expires_at = Column(
        DateTime,
        nullable=True,
        index=True,
        comment="When this exclusion expires (NULL for permanent exclusions)",
    )

    # Timestamps
    created_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False,
        comment="Exclusion creation timestamp",
    )

    # Relationships
    user = relationship("User", back_populates="search_exclusions")
    instance = relationship("Instance", back_populates="search_exclusions")

    def __repr__(self) -> str:
        """String representation of SearchExclusion."""
        return (
            f"<SearchExclusion(id={self.id}, title='{self.title}', "
            f"type='{self.content_type}', expires_at={self.expires_at})>"
        )

    @property
    def is_active(self) -> bool:
        """
        Check if the exclusion is currently active.

        An exclusion is active if:
        1. It has no expiration (permanent), or
        2. The expiration time is in the future

        Returns:
            bool: True if exclusion is active
        """
        if self.expires_at is None:
            return True
        return datetime.utcnow() < self.expires_at

    @property
    def expiry_label(self) -> str:
        """
        Get a human-readable expiry label.

        Returns:
            str: "Permanent" or formatted date string
        """
        if self.expires_at is None:
            return "Permanent"
        return self.expires_at.strftime("%Y-%m-%d")
