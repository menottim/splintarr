"""
Instance model for Sonarr/Radarr connections.

This module defines the Instance model for storing and managing connections
to Sonarr and Radarr instances with encrypted API keys.
"""

from datetime import datetime
from typing import Literal
from urllib.parse import urlparse, urlunparse

from sqlalchemy import Boolean, Column, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from splintarr.database import Base

# Instance types
InstanceType = Literal["sonarr", "radarr"]


class Instance(Base):
    """
    Instance model for Sonarr/Radarr API connections.

    Stores connection details for media management instances with:
    - Encrypted API keys (using Fernet from core.security)
    - Connection health tracking
    - User ownership
    - Configuration settings
    """

    __tablename__ = "instances"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # User relationship
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="User who owns this instance",
    )

    # Instance identification
    name = Column(
        String(100),
        nullable=False,
        comment="User-friendly name for this instance",
    )
    instance_type = Column(
        Enum("sonarr", "radarr", name="instance_type_enum"),
        nullable=False,
        index=True,
        comment="Type of instance (sonarr or radarr)",
    )

    # Connection details
    url = Column(
        String(255),
        nullable=False,
        comment="Base URL of the instance (e.g., https://sonarr.example.com)",
    )
    api_key = Column(
        Text,
        nullable=False,
        comment="Encrypted API key for instance authentication (Fernet encrypted)",
    )

    # Connection health
    is_active = Column(
        Boolean,
        default=True,
        nullable=False,
        comment="Whether this instance is active and should be used",
    )
    last_connection_test = Column(
        DateTime,
        nullable=True,
        comment="Last time connection was tested",
    )
    last_connection_success = Column(
        Boolean,
        nullable=True,
        comment="Result of last connection test (NULL if never tested)",
    )
    connection_error = Column(
        Text,
        nullable=True,
        comment="Error message from last failed connection attempt",
    )

    # Health monitoring (v0.2.1)
    consecutive_failures = Column(
        Integer,
        default=0,
        nullable=False,
        comment="Number of consecutive failed connection tests",
    )
    consecutive_successes = Column(
        Integer,
        default=0,
        nullable=False,
        comment="Number of consecutive successful connection tests",
    )
    last_healthy_at = Column(
        DateTime,
        nullable=True,
        comment="Timestamp of last successful health check",
    )
    response_time_ms = Column(
        Integer,
        nullable=True,
        comment="Response time of last connection test in milliseconds",
    )

    # Configuration
    verify_ssl = Column(
        Boolean,
        default=True,
        nullable=False,
        comment="Whether to verify SSL certificates (should be True in production)",
    )
    timeout_seconds = Column(
        Integer,
        default=30,
        nullable=False,
        comment="HTTP request timeout in seconds",
    )

    # Rate limiting (per-instance)
    rate_limit_per_second = Column(
        Float,
        default=5.0,
        nullable=False,
        comment="Maximum requests per second to this instance",
    )

    # Timestamps
    created_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False,
        comment="Instance creation timestamp",
    )
    updated_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="Last instance update timestamp",
    )

    # Relationships
    user = relationship("User", back_populates="instances")
    search_queues = relationship(
        "SearchQueue",
        back_populates="instance",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    search_history = relationship(
        "SearchHistory",
        back_populates="instance",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    library_items = relationship(
        "LibraryItem",
        back_populates="instance",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    search_exclusions = relationship(
        "SearchExclusion",
        back_populates="instance",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        """String representation of Instance."""
        return (
            f"<Instance(id={self.id}, name='{self.name}', "
            f"type='{self.instance_type}', active={self.is_active})>"
        )

    def is_healthy(self) -> bool:
        """
        Check if the instance connection is healthy.

        Returns:
            bool: True if last connection test was successful
        """
        return self.last_connection_success is True

    def record_connection_test(
        self, success: bool, error: str | None = None, response_time_ms: int | None = None
    ) -> None:
        """Record the result of a connection test."""
        self.last_connection_test = datetime.utcnow()
        self.last_connection_success = success
        self.connection_error = error if not success else None
        self.response_time_ms = response_time_ms

    def mark_healthy(self, response_time_ms: int | None = None) -> None:
        """Mark instance as healthy after a successful connection test."""
        self.record_connection_test(success=True, response_time_ms=response_time_ms)
        self.consecutive_failures = 0
        self.consecutive_successes = (self.consecutive_successes or 0) + 1
        self.last_healthy_at = datetime.utcnow()

    def mark_unhealthy(self, error: str) -> None:
        """Mark instance as unhealthy after a failed connection test."""
        self.record_connection_test(success=False, error=error)
        self.consecutive_failures = (self.consecutive_failures or 0) + 1
        self.consecutive_successes = 0

    @property
    def connection_status(self) -> str:
        """
        Get a human-readable connection status.

        Returns:
            str: Status description (e.g., "healthy", "unhealthy", "untested")
        """
        if self.last_connection_test is None:
            return "untested"

        if self.last_connection_success:
            return "healthy"

        return "unhealthy"

    @property
    def sanitized_url(self) -> str:
        """
        Get URL without sensitive information.

        Returns:
            str: URL with basic auth credentials removed
        """
        parsed = urlparse(self.url)
        if parsed.username or parsed.password:
            # Reconstruct URL without credentials
            netloc = parsed.hostname
            if parsed.port:
                netloc = f"{netloc}:{parsed.port}"
            parsed = parsed._replace(netloc=netloc)

        return urlunparse(parsed)
