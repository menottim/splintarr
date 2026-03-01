"""
Feedback Check Service for Splintarr.

Polls Sonarr/Radarr command statuses after searches to detect whether
content was actually grabbed, closing the search-result feedback loop.

The service:
1. Loads a completed SearchHistory record and parses its search_metadata
2. For each entry with a command_id, checks command completion status
3. Verifies whether the target item now has a file (grab confirmed)
4. Updates LibraryItem.record_grab() on confirmed grabs
5. Enriches search_metadata with grab_confirmed flags
"""

import json
from typing import Any

import structlog
from sqlalchemy.orm import Session

from splintarr.core.security import decrypt_api_key
from splintarr.models.instance import Instance
from splintarr.models.library import LibraryItem
from splintarr.models.search_history import SearchHistory
from splintarr.services.radarr import RadarrClient
from splintarr.services.sonarr import SonarrClient

logger = structlog.get_logger()


class FeedbackCheckService:
    """Check results of completed search runs for grab confirmation.

    After a search queue executes, commands are submitted to Sonarr/Radarr.
    This service polls those commands after a configurable delay to determine
    whether the searches actually resulted in grabs, and records the outcomes
    on the corresponding LibraryItem rows.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    async def check_search_results(self, history_id: int, instance_id: int) -> dict[str, Any]:
        """Check results of a completed search run.

        Args:
            history_id: SearchHistory record to inspect.
            instance_id: Instance the search was executed against.

        Returns:
            dict with ``checked`` and ``grabs`` counts.
        """
        # Load SearchHistory
        history = self.db.query(SearchHistory).filter(SearchHistory.id == history_id).first()
        if not history:
            logger.warning("feedback_check_no_history", history_id=history_id)
            return {"checked": 0, "grabs": 0}

        # Parse search_metadata
        entries = self._parse_metadata(history)
        if entries is None:
            return {"checked": 0, "grabs": 0}

        # Filter to entries that have a command_id and a searchable action
        searchable_actions = {"EpisodeSearch", "MoviesSearch"}
        commands = [
            e
            for e in entries
            if e.get("action") in searchable_actions and e.get("command_id") is not None
        ]

        if not commands:
            logger.debug(
                "feedback_check_no_commands",
                history_id=history_id,
                total_entries=len(entries),
            )
            return {"checked": 0, "grabs": 0}

        # Load Instance
        instance = self.db.query(Instance).filter(Instance.id == instance_id).first()
        if not instance:
            logger.warning("feedback_check_no_instance", instance_id=instance_id)
            return {"checked": 0, "grabs": 0}

        logger.info(
            "feedback_check_started",
            history_id=history_id,
            instance_id=instance_id,
            commands_to_check=len(commands),
        )

        is_sonarr = instance.instance_type == "sonarr"
        content_type = "series" if is_sonarr else "movie"

        # Create typed client
        try:
            api_key = decrypt_api_key(instance.api_key)
        except Exception as e:
            logger.error(
                "feedback_check_client_failed",
                instance_id=instance_id,
                error=str(e),
            )
            return {"checked": 0, "grabs": 0}

        client_cls = SonarrClient if is_sonarr else RadarrClient
        checked = 0
        grabs = 0

        try:
            async with client_cls(
                url=instance.url,
                api_key=api_key,
                verify_ssl=instance.verify_ssl,
                rate_limit_per_second=instance.rate_limit_per_second or 5,
            ) as client:
                for entry in commands:
                    command_id = entry["command_id"]
                    try:
                        grab_confirmed = await self._check_single_command(
                            client=client,
                            entry=entry,
                            is_sonarr=is_sonarr,
                        )
                        entry["grab_confirmed"] = grab_confirmed
                        checked += 1

                        if grab_confirmed:
                            grabs += 1
                            # Update LibraryItem
                            self._record_grab_on_library_item(
                                instance_id=instance_id,
                                content_type=content_type,
                                entry=entry,
                            )
                    except Exception as e:
                        logger.warning(
                            "feedback_check_command_failed",
                            command_id=command_id,
                            error=str(e),
                        )
                        entry["grab_confirmed"] = None  # unknown
                        checked += 1

        except Exception as e:
            logger.error(
                "feedback_check_client_failed",
                instance_id=instance_id,
                error=str(e),
            )
            # Return partial results -- some entries may already be enriched
            self._save_metadata(history, entries)
            return {"checked": checked, "grabs": grabs}

        # Save enriched metadata back to history
        self._save_metadata(history, entries)

        logger.info(
            "feedback_check_completed",
            history_id=history_id,
            checked=checked,
            grabs=grabs,
        )

        return {"checked": checked, "grabs": grabs}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_metadata(self, history: SearchHistory) -> list[dict[str, Any]] | None:
        """Parse search_metadata JSON from a SearchHistory record.

        Returns None (with a warning log) if the metadata is missing or invalid.
        """
        if not history.search_metadata:
            logger.debug(
                "feedback_check_empty_metadata",
                history_id=history.id,
            )
            return None

        try:
            data = json.loads(history.search_metadata)
            if not isinstance(data, list):
                logger.warning(
                    "feedback_check_invalid_metadata",
                    history_id=history.id,
                )
                return None
            return data
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "feedback_check_invalid_metadata",
                history_id=history.id,
            )
            return None

    async def _check_single_command(
        self,
        client: SonarrClient | RadarrClient,
        entry: dict[str, Any],
        is_sonarr: bool,
    ) -> bool:
        """Check a single command and return whether a grab was confirmed."""
        command_id = entry["command_id"]

        # Check command completion
        status = await client.get_command_status(command_id)
        if status.get("status") != "completed":
            return False

        # Command completed -- check if item now has a file
        if is_sonarr:
            return await self._check_sonarr_episode(client, entry)
        else:
            return await self._check_radarr_movie(client, entry)

    async def _check_sonarr_episode(
        self,
        client: SonarrClient,
        entry: dict[str, Any],
    ) -> bool:
        """Check if a Sonarr episode now has a file."""
        series_id = entry.get("series_id")
        item_id = entry.get("item_id")
        if not series_id or not item_id:
            return False

        episodes = await client.get_episodes(series_id)
        for ep in episodes:
            if ep.get("id") == item_id and ep.get("hasFile") is True:
                return True
        return False

    async def _check_radarr_movie(
        self,
        client: RadarrClient,
        entry: dict[str, Any],
    ) -> bool:
        """Check if a Radarr movie now has a file."""
        item_id = entry.get("item_id")
        if not item_id:
            return False

        movie = await client.get_movies(item_id)
        if isinstance(movie, dict) and movie.get("hasFile") is True:
            return True
        return False

    def _record_grab_on_library_item(
        self,
        instance_id: int,
        content_type: str,
        entry: dict[str, Any],
    ) -> None:
        """Update LibraryItem.record_grab() for a confirmed grab."""
        # Determine the external_id (series_id for Sonarr, item_id for Radarr)
        if content_type == "series":
            external_id = entry.get("series_id")
        else:
            external_id = entry.get("item_id")

        if not external_id:
            return

        library_item = (
            self.db.query(LibraryItem)
            .filter(
                LibraryItem.instance_id == instance_id,
                LibraryItem.external_id == external_id,
                LibraryItem.content_type == content_type,
            )
            .first()
        )

        if library_item:
            library_item.record_grab()
            logger.info(
                "feedback_grab_confirmed",
                instance_id=instance_id,
                external_id=external_id,
                content_type=content_type,
                title=library_item.title,
            )

    def _save_metadata(self, history: SearchHistory, entries: list[dict[str, Any]]) -> None:
        """Re-serialize enriched entries back to search_metadata and commit."""
        try:
            history.search_metadata = json.dumps(entries)
            self.db.commit()
        except Exception as e:
            logger.warning(
                "feedback_check_metadata_save_failed",
                history_id=history.id,
                error=str(e),
            )
