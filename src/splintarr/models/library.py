"""
Library item and episode models for Sonarr/Radarr sync cache.

Stores a read-only local mirror of series/movie data pulled from connected
instances. Updated on sync; never written by user action.
"""

import json
from typing import Any

import structlog
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from splintarr.database import Base

logger = structlog.get_logger()


class LibraryItem(Base):
    """
    Cached library entry from a Sonarr or Radarr instance.

    One row per series (Sonarr) or movie (Radarr) per instance.
    Refreshed on each sync cycle; poster_path is a local filesystem path.
    """

    __tablename__ = "library_items"
    __table_args__ = (
        UniqueConstraint(
            "instance_id",
            "content_type",
            "external_id",
            name="uq_library_item_instance_external",
        ),
    )

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Instance relationship
    instance_id = Column(
        Integer,
        ForeignKey("instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Instance this item was synced from",
    )

    # Content identification
    content_type = Column(
        Enum("series", "movie", name="library_content_type_enum"),
        nullable=False,
        index=True,
        comment="Type of content (series for Sonarr, movie for Radarr)",
    )
    external_id = Column(
        Integer,
        nullable=False,
        index=True,
        comment="ID in the source instance (series.id or movie.id)",
    )

    # Display fields
    title = Column(
        String(500),
        nullable=False,
        comment="Series or movie title",
    )
    year = Column(
        Integer,
        nullable=True,
        comment="Release year",
    )
    status = Column(
        String(50),
        nullable=True,
        index=True,
        comment="Series/movie status (e.g. continuing, ended, released)",
    )
    quality_profile = Column(
        String(100),
        nullable=True,
        comment="Quality profile name or ID from the instance",
    )

    # Completeness tracking
    episode_count = Column(
        Integer,
        default=0,
        nullable=False,
        comment="Total monitored episodes (Sonarr) or 1 (Radarr)",
    )
    episode_have = Column(
        Integer,
        default=0,
        nullable=False,
        comment="Downloaded episodes (Sonarr) or 1 if file exists (Radarr)",
    )

    # Poster
    poster_path = Column(
        String(500),
        nullable=True,
        comment=(
            "Relative path to cached poster: "
            "{instance_id}/{content_type}/{external_id}.jpg"
        ),
    )

    # Raw API data
    metadata_json = Column(
        Text,
        nullable=True,
        comment="Truncated JSON from last sync for debugging and future fields",
    )

    # Sync tracking
    last_synced_at = Column(
        DateTime,
        nullable=True,
        index=True,
        comment="UTC timestamp of last successful sync for this item",
    )
    added_at = Column(
        DateTime,
        nullable=True,
        comment="Date the item was added to the *arr instance (from API)",
    )

    # Timestamps
    created_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False,
        comment="Row creation timestamp",
    )
    updated_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="Last row update timestamp",
    )

    # Relationships
    instance = relationship("Instance", back_populates="library_items")
    episodes = relationship(
        "LibraryEpisode",
        back_populates="library_item",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        """String representation of LibraryItem."""
        return (
            f"<LibraryItem(id={self.id}, title='{self.title}', "
            f"type='{self.content_type}', instance_id={self.instance_id})>"
        )

    @property
    def completion_pct(self) -> float:
        """Percentage of monitored content downloaded (0.0-100.0)."""
        count = self.episode_count or 0
        have = self.episode_have or 0
        if count == 0:
            return 0.0
        return round(have / count * 100, 1)

    @property
    def is_complete(self) -> bool:
        """True if all monitored content is downloaded."""
        count = self.episode_count or 0
        have = self.episode_have or 0
        return count > 0 and have >= count

    @property
    def missing_count(self) -> int:
        """Number of monitored items not yet downloaded."""
        return max(0, (self.episode_count or 0) - (self.episode_have or 0))

    def get_metadata(self) -> dict[str, Any]:
        """Deserialize metadata_json to dict (empty dict on failure)."""
        if not self.metadata_json:
            return {}
        try:
            result = json.loads(self.metadata_json)
            if not isinstance(result, dict):
                return {}
            return result
        except (ValueError, TypeError):
            logger.warning(
                "metadata_json_parse_failed",
                library_item_id=self.id,
            )
            return {}


class LibraryEpisode(Base):
    """
    Individual episode record for a Sonarr series in the library cache.

    Only populated for content_type='series'. Radarr items use LibraryItem
    episode_count/episode_have fields directly.
    """

    __tablename__ = "library_episodes"
    __table_args__ = (
        UniqueConstraint(
            "library_item_id",
            "season_number",
            "episode_number",
            name="uq_library_episode_item_season_episode",
        ),
    )

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Parent series
    library_item_id = Column(
        Integer,
        ForeignKey("library_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Parent library item (series)",
    )

    # Episode identification
    season_number = Column(
        Integer,
        nullable=False,
        comment="Season number",
    )
    episode_number = Column(
        Integer,
        nullable=False,
        comment="Episode number within season",
    )
    title = Column(
        String(500),
        nullable=True,
        comment="Episode title",
    )

    # Status
    air_date = Column(
        DateTime,
        nullable=True,
        comment="Original air date",
    )
    has_file = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="Whether the episode file is downloaded",
    )
    monitored = Column(
        Boolean,
        default=True,
        nullable=False,
        comment="Whether the episode is monitored in Sonarr",
    )

    # Timestamps
    created_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False,
        comment="Row creation timestamp",
    )
    updated_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="Last row update timestamp",
    )

    # Relationships
    library_item = relationship("LibraryItem", back_populates="episodes")

    def __repr__(self) -> str:
        """String representation of LibraryEpisode."""
        sn = f"{self.season_number:02d}" if self.season_number is not None else "?"
        en = f"{self.episode_number:02d}" if self.episode_number is not None else "?"
        return (
            f"<LibraryEpisode(id={self.id}, S{sn}E{en}, "
            f"has_file={self.has_file})>"
        )

    @property
    def episode_code(self) -> str:
        """Format as S01E05 style code."""
        sn = f"{self.season_number:02d}" if self.season_number is not None else "?"
        en = f"{self.episode_number:02d}" if self.episode_number is not None else "?"
        return f"S{sn}E{en}"
