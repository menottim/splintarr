"""
Library Sync Service for Splintarr.

Pulls series/movie data from connected Sonarr/Radarr instances and caches
it locally in the library_items and library_episodes tables. Poster images
are downloaded to a local directory for serving via static mount.
"""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy.orm import Session

from splintarr.core.security import decrypt_api_key
from splintarr.models import Instance
from splintarr.models.library import LibraryEpisode, LibraryItem
from splintarr.services.radarr import RadarrClient
from splintarr.services.sonarr import SonarrClient

logger = structlog.get_logger()

# Default poster storage directory (inside the Docker data volume)
POSTER_BASE_DIR = Path("data/posters")


class LibrarySyncError(Exception):
    """Error during library sync."""

    pass


class LibrarySyncService:
    """
    Service for syncing library data from Sonarr/Radarr instances.

    Pulls series/movie lists, caches poster images, and maintains
    episode-level tracking for Sonarr series.
    """

    def __init__(
        self,
        db_session_factory: Callable[[], Session],
        poster_dir: Path | None = None,
    ):
        self.db_session_factory = db_session_factory
        self.poster_dir = poster_dir or POSTER_BASE_DIR
        logger.info("library_sync_service_initialized")

    async def sync_all_instances(self) -> dict[str, Any]:
        """
        Sync library data from all active instances.

        Returns:
            dict: Summary with instance_count, items_synced, errors
        """
        db = self.db_session_factory()
        total_items = 0
        errors: list[str] = []

        try:
            instances = db.query(Instance).filter(Instance.is_active.is_(True)).all()

            logger.info("library_sync_started", instance_count=len(instances))

            for instance in instances:
                try:
                    count = await self._sync_instance(instance, db)
                    total_items += count
                except Exception as e:
                    error_msg = f"{instance.name}: {e}"
                    errors.append(error_msg)
                    logger.error(
                        "library_sync_instance_failed",
                        instance_id=instance.id,
                        instance_name=instance.name,
                        instance_type=instance.instance_type,
                        error=str(e),
                    )

            logger.info(
                "library_sync_completed",
                items_synced=total_items,
                errors=len(errors),
            )

            return {
                "instance_count": len(instances),
                "items_synced": total_items,
                "errors": errors,
            }

        finally:
            db.close()

    async def sync_instance(self, instance_id: int) -> int:
        """
        Sync a single instance by ID.

        Args:
            instance_id: Instance to sync

        Returns:
            int: Number of items synced

        Raises:
            LibrarySyncError: If instance not found
        """
        db = self.db_session_factory()
        try:
            instance = db.query(Instance).filter(Instance.id == instance_id).first()
            if not instance:
                raise LibrarySyncError(f"Instance {instance_id} not found")
            return await self._sync_instance(instance, db)
        finally:
            db.close()

    async def _sync_instance(self, instance: Instance, db: Session) -> int:
        """Sync library data from a single instance."""
        logger.info(
            "library_sync_instance_started",
            instance_id=instance.id,
            instance_name=instance.name,
            instance_type=instance.instance_type,
        )
        api_key = decrypt_api_key(instance.api_key)
        now = datetime.utcnow()

        if instance.instance_type == "sonarr":
            return await self._sync_sonarr(instance, api_key, db, now)
        else:
            return await self._sync_radarr(instance, api_key, db, now)

    async def _sync_sonarr(
        self,
        instance: Instance,
        api_key: str,
        db: Session,
        now: datetime,
    ) -> int:
        """Sync all series and episodes from a Sonarr instance."""
        count = 0
        seen_external_ids: set[int] = set()

        logger.info("library_sync_sonarr_started", instance_id=instance.id)

        async with SonarrClient(
            url=instance.url,
            api_key=api_key,
            verify_ssl=instance.verify_ssl,
            rate_limit_per_second=instance.rate_limit_per_second or 5,
        ) as client:
            series_list = await client.get_series()
            if not isinstance(series_list, list):
                series_list = []

            logger.info(
                "library_sync_sonarr_series_fetched",
                instance_id=instance.id,
                series_count=len(series_list),
            )

            for series in series_list:
                try:
                    external_id = series.get("id")
                    if not external_id:
                        continue

                    seen_external_ids.add(external_id)
                    stats = series.get("statistics", {})

                    item = self._upsert_library_item(
                        db=db,
                        instance_id=instance.id,
                        content_type="series",
                        external_id=external_id,
                        title=series.get("title", "Unknown"),
                        year=series.get("year"),
                        status=series.get("status"),
                        quality_profile=str(series.get("qualityProfileId", "")),
                        episode_count=stats.get("episodeCount", 0),
                        episode_have=stats.get("episodeFileCount", 0),
                        added_at=series.get("added"),
                        now=now,
                    )

                    # Sync episodes
                    episodes = await client.get_episodes(external_id)
                    self._upsert_episodes(db, item.id, episodes)

                    count += 1

                except Exception as e:
                    logger.warning(
                        "library_sync_series_failed",
                        instance_id=instance.id,
                        series_id=series.get("id"),
                        error=str(e),
                    )

            db.commit()
            logger.debug(
                "library_sync_sonarr_items_committed",
                instance_id=instance.id,
                items=count,
            )

            await self._download_posters(client, db, instance.id, "series", series_list)
            db.commit()

        # Remove items no longer in the instance
        stale_count = self._cleanup_stale_items(db, instance.id, "series", seen_external_ids)
        db.commit()

        logger.info(
            "library_sync_sonarr_completed",
            instance_id=instance.id,
            items_synced=count,
            stale_removed=stale_count,
        )
        return count

    async def _sync_radarr(
        self,
        instance: Instance,
        api_key: str,
        db: Session,
        now: datetime,
    ) -> int:
        """Sync all movies from a Radarr instance."""
        count = 0
        seen_external_ids: set[int] = set()

        logger.info("library_sync_radarr_started", instance_id=instance.id)

        async with RadarrClient(
            url=instance.url,
            api_key=api_key,
            verify_ssl=instance.verify_ssl,
            rate_limit_per_second=instance.rate_limit_per_second or 5,
        ) as client:
            movie_list = await client.get_movies()
            if not isinstance(movie_list, list):
                movie_list = []

            logger.info(
                "library_sync_radarr_movies_fetched",
                instance_id=instance.id,
                movie_count=len(movie_list),
            )

            for movie in movie_list:
                try:
                    external_id = movie.get("id")
                    if not external_id:
                        continue

                    seen_external_ids.add(external_id)
                    has_file = movie.get("hasFile", False)

                    self._upsert_library_item(
                        db=db,
                        instance_id=instance.id,
                        content_type="movie",
                        external_id=external_id,
                        title=movie.get("title", "Unknown"),
                        year=movie.get("year"),
                        status=movie.get("status"),
                        quality_profile=str(movie.get("qualityProfileId", "")),
                        episode_count=1,
                        episode_have=1 if has_file else 0,
                        added_at=movie.get("added"),
                        now=now,
                    )

                    count += 1

                except Exception as e:
                    logger.warning(
                        "library_sync_movie_failed",
                        instance_id=instance.id,
                        movie_id=movie.get("id"),
                        error=str(e),
                    )

            db.commit()
            logger.debug(
                "library_sync_radarr_items_committed",
                instance_id=instance.id,
                items=count,
            )

            await self._download_posters(client, db, instance.id, "movie", movie_list)
            db.commit()

        # Remove stale items
        stale_count = self._cleanup_stale_items(db, instance.id, "movie", seen_external_ids)
        db.commit()

        logger.info(
            "library_sync_radarr_completed",
            instance_id=instance.id,
            items_synced=count,
            stale_removed=stale_count,
        )
        return count

    async def _download_posters(
        self,
        client: SonarrClient | RadarrClient,
        db: Session,
        instance_id: int,
        content_type: str,
        items_list: list[dict[str, Any]],
    ) -> None:
        """Download and cache poster images for items missing a poster_path."""
        for raw_item in items_list:
            ext_id = raw_item.get("id")
            if not ext_id:
                continue
            item = (
                db.query(LibraryItem)
                .filter(
                    LibraryItem.instance_id == instance_id,
                    LibraryItem.content_type == content_type,
                    LibraryItem.external_id == ext_id,
                )
                .first()
            )
            if not item or item.poster_path:
                continue
            rel = f"{instance_id}/{content_type}/{ext_id}.jpg"
            if (self.poster_dir / rel).exists():
                item.poster_path = rel
            else:
                poster_data = await client.get_poster_bytes(ext_id)
                if poster_data:
                    item.poster_path = self._save_poster(
                        instance_id, content_type, ext_id, poster_data
                    )
                    logger.debug(
                        "library_sync_poster_saved",
                        instance_id=instance_id,
                        content_type=content_type,
                        external_id=ext_id,
                        size_bytes=len(poster_data),
                    )

    def _upsert_library_item(
        self,
        db: Session,
        instance_id: int,
        content_type: str,
        external_id: int,
        title: str,
        year: int | None,
        status: str | None,
        quality_profile: str | None,
        episode_count: int,
        episode_have: int,
        added_at: str | None,
        now: datetime,
    ) -> LibraryItem:
        """Insert or update a library item."""
        item = (
            db.query(LibraryItem)
            .filter(
                LibraryItem.instance_id == instance_id,
                LibraryItem.content_type == content_type,
                LibraryItem.external_id == external_id,
            )
            .first()
        )

        parsed_added = None
        if added_at:
            try:
                parsed_added = datetime.fromisoformat(added_at.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                logger.debug(
                    "library_sync_date_parse_failed",
                    content_type=content_type,
                    external_id=external_id,
                    raw_value=added_at,
                )

        if item:
            item.title = title
            item.year = year
            item.status = status
            item.quality_profile = quality_profile
            item.episode_count = episode_count
            item.episode_have = episode_have
            item.last_synced_at = now
            if parsed_added:
                item.added_at = parsed_added
            logger.debug(
                "library_sync_item_updated",
                content_type=content_type,
                external_id=external_id,
                title=title,
            )
        else:
            item = LibraryItem(
                instance_id=instance_id,
                content_type=content_type,
                external_id=external_id,
                title=title,
                year=year,
                status=status,
                quality_profile=quality_profile,
                episode_count=episode_count,
                episode_have=episode_have,
                last_synced_at=now,
                added_at=parsed_added,
            )
            db.add(item)
            db.flush()
            logger.debug(
                "library_sync_item_created",
                content_type=content_type,
                external_id=external_id,
                title=title,
            )

        return item

    def _upsert_episodes(
        self,
        db: Session,
        library_item_id: int,
        episodes: list[dict[str, Any]],
    ) -> None:
        """Upsert episode records for a series, removing stale ones."""
        seen_keys: set[tuple[int, int]] = set()

        for ep in episodes:
            season = ep.get("seasonNumber")
            ep_num = ep.get("episodeNumber")
            if season is None or ep_num is None:
                continue

            seen_keys.add((season, ep_num))

            existing = (
                db.query(LibraryEpisode)
                .filter(
                    LibraryEpisode.library_item_id == library_item_id,
                    LibraryEpisode.season_number == season,
                    LibraryEpisode.episode_number == ep_num,
                )
                .first()
            )

            air_date = None
            if ep.get("airDateUtc"):
                try:
                    air_date = datetime.fromisoformat(ep["airDateUtc"].replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    logger.debug(
                        "library_sync_episode_date_parse_failed",
                        library_item_id=library_item_id,
                        season=season,
                        episode=ep_num,
                    )

            if existing:
                existing.title = ep.get("title")
                existing.air_date = air_date
                existing.has_file = ep.get("hasFile", False)
                existing.monitored = ep.get("monitored", True)
            else:
                db.add(
                    LibraryEpisode(
                        library_item_id=library_item_id,
                        season_number=season,
                        episode_number=ep_num,
                        title=ep.get("title"),
                        air_date=air_date,
                        has_file=ep.get("hasFile", False),
                        monitored=ep.get("monitored", True),
                    )
                )

        # Delete episodes no longer in the API response
        all_existing = (
            db.query(LibraryEpisode).filter(LibraryEpisode.library_item_id == library_item_id).all()
        )
        deleted_count = 0
        for existing_ep in all_existing:
            key = (existing_ep.season_number, existing_ep.episode_number)
            if key not in seen_keys:
                db.delete(existing_ep)
                deleted_count += 1

        logger.debug(
            "library_sync_episodes_upserted",
            library_item_id=library_item_id,
            total_episodes=len(seen_keys),
            stale_deleted=deleted_count,
        )

    def _cleanup_stale_items(
        self,
        db: Session,
        instance_id: int,
        content_type: str,
        seen_ids: set[int],
    ) -> int:
        """Delete library items no longer in the instance. Returns count removed."""
        if not seen_ids:
            # No items were successfully synced — skip cleanup to avoid
            # deleting everything when the API is temporarily unreachable.
            logger.warning(
                "library_sync_cleanup_skipped_empty",
                instance_id=instance_id,
                content_type=content_type,
            )
            return 0

        stale = (
            db.query(LibraryItem)
            .filter(
                LibraryItem.instance_id == instance_id,
                LibraryItem.content_type == content_type,
                ~LibraryItem.external_id.in_(seen_ids),
            )
            .all()
        )
        for item in stale:
            # Clean up poster file from disk
            if item.poster_path:
                poster_file = self.poster_dir / item.poster_path
                if poster_file.exists():
                    poster_file.unlink()
                    logger.debug(
                        "library_sync_poster_file_removed",
                        path=str(poster_file),
                    )
            logger.info(
                "library_sync_removing_stale_item",
                instance_id=instance_id,
                content_type=content_type,
                item_id=item.id,
                title=item.title,
            )
            db.delete(item)
        return len(stale)

    def _save_poster(
        self,
        instance_id: int,
        content_type: str,
        external_id: int,
        data: bytes,
    ) -> str:
        """Write poster bytes to disk and return the relative path."""
        rel_path = f"{instance_id}/{content_type}/{external_id}.jpg"
        full_path = self.poster_dir / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(data)
        return rel_path


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_sync_service: LibrarySyncService | None = None


def get_sync_service(
    db_session_factory: Callable[[], Session] | None = None,
    poster_dir: Path | None = None,
) -> LibrarySyncService:
    """Get or create the library sync service singleton."""
    global _sync_service
    if _sync_service is None:
        if db_session_factory is None:
            raise RuntimeError("db_session_factory required on first call")
        _sync_service = LibrarySyncService(db_session_factory, poster_dir=poster_dir)
    return _sync_service
