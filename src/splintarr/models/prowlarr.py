"""
ProwlarrConfig database model.

This module defines the ProwlarrConfig model for storing Prowlarr connection
settings per user, with encrypted API keys and configurable sync intervals.
Singleton-per-user: each user can have at most one Prowlarr connection.
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from splintarr.database import Base


class ProwlarrConfig(Base):
    """
    ProwlarrConfig model for Prowlarr indexer management connection.

    Stores per-user Prowlarr connection settings including:
    - Fernet-encrypted API key
    - Sync interval for periodic indexer data refresh
    - SSL verification toggle
    - Active/inactive toggle
    - Last sync timestamp for scheduling awareness
    """

    __tablename__ = "prowlarr_configs"

    # Primary key
    id = Column(
        Integer,
        primary_key=True,
        index=True,
        comment="Unique Prowlarr config identifier",
    )

    # User relationship (singleton per user)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
        comment="User who owns this Prowlarr config",
    )

    # Connection details
    url = Column(
        String(255),
        nullable=False,
        comment="Base URL of the Prowlarr instance (e.g., http://prowlarr:9696)",
    )
    encrypted_api_key = Column(
        Text,
        nullable=False,
        comment="Fernet-encrypted API key for Prowlarr authentication",
    )

    # Connection configuration
    verify_ssl = Column(
        Boolean,
        default=True,
        nullable=False,
        comment="Whether to verify SSL certificates for the Prowlarr connection",
    )

    # Sync configuration
    sync_interval_minutes = Column(
        Integer,
        default=60,
        nullable=False,
        comment="How often to sync indexer data from Prowlarr (in minutes)",
    )

    # Active toggle
    is_active = Column(
        Boolean,
        default=True,
        nullable=False,
        comment="Whether Prowlarr integration is currently enabled",
    )

    # Tracking
    last_sync_at = Column(
        DateTime,
        nullable=True,
        comment="Timestamp of most recent successful indexer sync from Prowlarr",
    )

    # Timestamps
    created_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False,
        comment="Config creation timestamp",
    )
    updated_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="Last config update timestamp",
    )

    # Relationships
    user = relationship("User", back_populates="prowlarr_config")

    def __repr__(self) -> str:
        """String representation of ProwlarrConfig."""
        return f"<ProwlarrConfig(id={self.id}, user_id={self.user_id}, is_active={self.is_active})>"
