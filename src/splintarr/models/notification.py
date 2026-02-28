"""
NotificationConfig database model.

This module defines the NotificationConfig model for storing Discord webhook
notification settings per user, with encrypted webhook URLs and configurable
event subscriptions.
"""

import json
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from splintarr.database import Base


# Default events configuration — all enabled by default
DEFAULT_EVENTS: dict[str, bool] = {
    "search_triggered": True,
    "queue_failed": True,
    "instance_health": True,
    "library_sync": True,
}


class NotificationConfig(Base):
    """
    NotificationConfig model for Discord webhook notification settings.

    Stores per-user notification preferences including:
    - Fernet-encrypted Discord webhook URL
    - JSON-encoded event subscription flags
    - Active/inactive toggle
    - Timestamp tracking for rate limiting awareness
    """

    __tablename__ = "notification_configs"

    # Primary key
    id = Column(
        Integer,
        primary_key=True,
        index=True,
        comment="Unique notification config identifier",
    )

    # User relationship
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
        comment="User who owns this notification config",
    )

    # Webhook configuration
    webhook_url = Column(
        Text,
        nullable=False,
        comment="Fernet-encrypted Discord webhook URL",
    )

    # Event subscriptions (JSON string)
    events_enabled = Column(
        Text,
        nullable=False,
        default=json.dumps(DEFAULT_EVENTS),
        comment="JSON object mapping event names to enabled/disabled booleans",
    )

    # Active toggle
    is_active = Column(
        Boolean,
        default=True,
        nullable=False,
        comment="Whether notifications are currently enabled",
    )

    # Tracking
    last_sent_at = Column(
        DateTime,
        nullable=True,
        comment="Timestamp of most recently sent notification",
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
    user = relationship("User", back_populates="notification_config")

    def __repr__(self) -> str:
        """String representation of NotificationConfig."""
        return (
            f"<NotificationConfig(id={self.id}, user_id={self.user_id}, "
            f"is_active={self.is_active})>"
        )

    def get_events(self) -> dict[str, bool]:
        """
        Parse the events_enabled JSON string into a dictionary.

        Returns:
            dict: Event names mapped to enabled/disabled booleans.
                  Returns defaults if parsing fails.
        """
        if not self.events_enabled:
            return DEFAULT_EVENTS.copy()

        try:
            events: dict[str, Any] = json.loads(self.events_enabled)
            return {k: bool(v) for k, v in events.items()}
        except (json.JSONDecodeError, TypeError):
            return DEFAULT_EVENTS.copy()

    def set_events(self, events: dict[str, bool]) -> None:
        """
        Serialize an events dictionary to JSON and store it.

        Args:
            events: Event names mapped to enabled/disabled booleans
        """
        self.events_enabled = json.dumps(events)

    def is_event_enabled(self, event_name: str) -> bool:
        """
        Check if a specific event type is enabled.

        Args:
            event_name: Name of the event (e.g. 'search_triggered')

        Returns:
            bool: True if the event is enabled
        """
        events = self.get_events()
        return events.get(event_name, False)
