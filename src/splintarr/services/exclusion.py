"""
Exclusion Service for Splintarr.

This module implements content exclusion list management:
- Query active exclusions for search filtering
- Create, delete, and list exclusion entries
- Duration-based expiry calculation
- Idempotent creation (no duplicates)
"""

from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy.orm import Session

from splintarr.models.exclusion import SearchExclusion

logger = structlog.get_logger()

# Duration presets: label -> timedelta (None = permanent)
DURATION_MAP: dict[str, timedelta | None] = {
    "permanent": None,
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
}


class ExclusionService:
    """
    Service for managing content exclusion lists.

    Provides methods to create, delete, list, and query exclusions
    that prevent specific content from being searched automatically.
    """

    def __init__(self, db_session_factory: Any) -> None:
        """
        Initialize ExclusionService.

        Args:
            db_session_factory: Factory function or sessionmaker to create database sessions
        """
        self.db_session_factory = db_session_factory

    def get_active_exclusion_keys(
        self,
        user_id: int,
        instance_id: int,
    ) -> set[tuple[int, str]]:
        """
        Get a set of (external_id, content_type) tuples for all active exclusions.

        Loads all active exclusions for the given user and instance in one query.
        Used by the search queue to skip excluded items efficiently.

        Args:
            user_id: ID of the user
            instance_id: ID of the instance

        Returns:
            set: Set of (external_id, content_type) tuples
        """
        db: Session = self.db_session_factory()
        try:
            now = datetime.utcnow()
            exclusions = (
                db.query(SearchExclusion.external_id, SearchExclusion.content_type)
                .filter(
                    SearchExclusion.user_id == user_id,
                    SearchExclusion.instance_id == instance_id,
                )
                .filter(
                    (SearchExclusion.expires_at.is_(None))
                    | (SearchExclusion.expires_at > now)
                )
                .all()
            )

            keys = {(row.external_id, row.content_type) for row in exclusions}

            logger.debug(
                "exclusion_keys_loaded",
                user_id=user_id,
                instance_id=instance_id,
                active_count=len(keys),
            )

            return keys

        except Exception as e:
            logger.error(
                "exclusion_keys_load_failed",
                user_id=user_id,
                instance_id=instance_id,
                error=str(e),
            )
            raise
        finally:
            db.close()

    def create_exclusion(
        self,
        user_id: int,
        instance_id: int,
        external_id: int,
        content_type: str,
        title: str,
        library_item_id: int | None = None,
        reason: str | None = None,
        duration: str = "permanent",
    ) -> SearchExclusion:
        """
        Create a content exclusion entry (idempotent).

        If an active exclusion already exists for the same user, instance,
        external_id, and content_type, the existing exclusion is returned
        without creating a duplicate.

        Args:
            user_id: ID of the user
            instance_id: ID of the instance
            external_id: ID of the item in the source instance
            content_type: "series" or "movie"
            title: Title of the content (for display)
            library_item_id: Optional local LibraryItem ID
            reason: Optional reason for exclusion
            duration: Duration preset ("permanent", "7d", "30d", "90d")

        Returns:
            SearchExclusion: The created or existing exclusion

        Raises:
            ValueError: If duration is not a valid preset
        """
        if duration not in DURATION_MAP:
            raise ValueError(
                f"Invalid duration '{duration}'. "
                f"Must be one of: {', '.join(DURATION_MAP.keys())}"
            )

        db: Session = self.db_session_factory()
        try:
            now = datetime.utcnow()

            # Check for existing active exclusion (idempotent)
            existing = (
                db.query(SearchExclusion)
                .filter(
                    SearchExclusion.user_id == user_id,
                    SearchExclusion.instance_id == instance_id,
                    SearchExclusion.external_id == external_id,
                    SearchExclusion.content_type == content_type,
                )
                .filter(
                    (SearchExclusion.expires_at.is_(None))
                    | (SearchExclusion.expires_at > now)
                )
                .first()
            )

            if existing:
                logger.info(
                    "exclusion_already_exists",
                    user_id=user_id,
                    instance_id=instance_id,
                    external_id=external_id,
                    content_type=content_type,
                    exclusion_id=existing.id,
                )
                return existing

            # Calculate expiry
            delta = DURATION_MAP[duration]
            expires_at = (now + delta) if delta is not None else None

            exclusion = SearchExclusion(
                user_id=user_id,
                instance_id=instance_id,
                external_id=external_id,
                content_type=content_type,
                title=title,
                library_item_id=library_item_id,
                reason=reason,
                expires_at=expires_at,
            )

            db.add(exclusion)
            db.commit()
            db.refresh(exclusion)

            logger.info(
                "exclusion_created",
                user_id=user_id,
                instance_id=instance_id,
                external_id=external_id,
                content_type=content_type,
                title=title,
                duration=duration,
                exclusion_id=exclusion.id,
            )

            return exclusion

        except Exception as e:
            db.rollback()
            logger.error(
                "exclusion_create_failed",
                user_id=user_id,
                instance_id=instance_id,
                external_id=external_id,
                content_type=content_type,
                error=str(e),
            )
            raise
        finally:
            db.close()

    def delete_exclusion(self, exclusion_id: int, user_id: int) -> bool:
        """
        Delete an exclusion by ID (user-scoped).

        Only deletes if the exclusion belongs to the given user.

        Args:
            exclusion_id: ID of the exclusion to delete
            user_id: ID of the user (ownership check)

        Returns:
            bool: True if deleted, False if not found or not owned
        """
        db: Session = self.db_session_factory()
        try:
            exclusion = (
                db.query(SearchExclusion)
                .filter(
                    SearchExclusion.id == exclusion_id,
                    SearchExclusion.user_id == user_id,
                )
                .first()
            )

            if not exclusion:
                logger.debug(
                    "exclusion_not_found_for_delete",
                    exclusion_id=exclusion_id,
                    user_id=user_id,
                )
                return False

            db.delete(exclusion)
            db.commit()

            logger.info(
                "exclusion_deleted",
                exclusion_id=exclusion_id,
                user_id=user_id,
                title=exclusion.title,
            )

            return True

        except Exception as e:
            db.rollback()
            logger.error(
                "exclusion_delete_failed",
                exclusion_id=exclusion_id,
                user_id=user_id,
                error=str(e),
            )
            raise
        finally:
            db.close()

    def list_exclusions(
        self,
        user_id: int,
        instance_id: int | None = None,
        include_expired: bool = False,
    ) -> list[SearchExclusion]:
        """
        List exclusions for a user, optionally filtered by instance.

        Args:
            user_id: ID of the user
            instance_id: Optional instance ID filter
            include_expired: If True, include expired exclusions

        Returns:
            list: List of SearchExclusion objects
        """
        db: Session = self.db_session_factory()
        try:
            query = db.query(SearchExclusion).filter(
                SearchExclusion.user_id == user_id,
            )

            if instance_id is not None:
                query = query.filter(SearchExclusion.instance_id == instance_id)

            if not include_expired:
                now = datetime.utcnow()
                query = query.filter(
                    (SearchExclusion.expires_at.is_(None))
                    | (SearchExclusion.expires_at > now)
                )

            exclusions = query.order_by(SearchExclusion.created_at.desc()).all()

            # Eagerly access instance relationship while session is open
            for exc in exclusions:
                _ = exc.instance

            logger.debug(
                "exclusions_listed",
                user_id=user_id,
                instance_id=instance_id,
                include_expired=include_expired,
                count=len(exclusions),
            )

            return exclusions

        except Exception as e:
            logger.error(
                "exclusions_list_failed",
                user_id=user_id,
                instance_id=instance_id,
                error=str(e),
            )
            raise
        finally:
            db.close()
