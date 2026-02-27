"""
Instance model for Sonarr/Radarr connections.

This module defines the Instance model for storing and managing connections
to Sonarr and Radarr instances with encrypted API keys.
"""

from datetime import datetime
from typing import Literal
from urllib.parse import urlparse, urlunparse

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text
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
        Integer,
        default=5,
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

    def record_connection_test(self, success: bool, error: str | None = None) -> None:
        """
        Record the result of a connection test.

        Args:
            success: Whether the connection test succeeded
            error: Error message if connection failed (optional)
        """
        self.last_connection_test = datetime.utcnow()
        self.last_connection_success = success
        self.connection_error = error if not success else None

    def mark_unhealthy(self, error: str) -> None:
        """
        Mark instance as unhealthy with an error message.

        Args:
            error: Error message describing the connection failure
        """
        self.record_connection_test(success=False, error=error)
        # Optionally deactivate after repeated failures
        # This could be enhanced with a failure counter

    def mark_healthy(self) -> None:
        """Mark instance as healthy and clear any error messages."""
        self.record_connection_test(success=True, error=None)

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
