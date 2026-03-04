"""
Search Queue Management Service for Splintarr.

This module implements search queue operations and execution:
- Queue CRUD operations (add, update, delete)
- Search strategy implementations (missing, cutoff, recent, custom)
- Priority scoring and intelligent item ordering
- Batch processing with rate limiting
- DB-backed tiered cooldown enforcement
- Integration with Sonarr/Radarr clients
- Search history tracking

The queue manager coordinates with the scheduler to execute automated searches
across configured instances.
"""

import json
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy.orm import Session

from splintarr.config import settings
from splintarr.core.events import event_bus
from splintarr.core.security import decrypt_api_key, decrypt_field
from splintarr.models import Instance, NotificationConfig, SearchHistory, SearchQueue
from splintarr.services.cooldown import is_in_cooldown
from splintarr.services.custom_filters import apply_custom_filters
from splintarr.services.discord import DiscordNotificationService
from splintarr.services.exclusion import ExclusionService
from splintarr.services.radarr import RadarrClient
from splintarr.services.scoring import compute_score
from splintarr.services.sonarr import SonarrClient

logger = structlog.get_logger()


def _episode_label(episode: dict[str, Any], library_items: dict[int, Any] | None = None) -> str:
    """Build a human-readable label from a Sonarr episode record.

    Falls back to library_items for the series title if the API record
    doesn't include nested series data.
    """
    series = episode.get("series", {})
    series_title = series.get("title") if series else None
    if not series_title and library_items:
        ext_id = episode.get("seriesId") or series.get("id") if series else None
        if ext_id and ext_id in library_items:
            series_title = getattr(library_items[ext_id], "title", None)
    if not series_title:
        series_title = "Unknown Series"
    season = episode.get("seasonNumber", "?")
    ep_num = episode.get("episodeNumber", "?")
    ep_title = episode.get("title", "")
    if isinstance(season, int) and isinstance(ep_num, int):
        label = f"{series_title} S{season:02d}E{ep_num:02d}"
    else:
        label = f"{series_title} S{season}E{ep_num}"
    if ep_title:
        label += f" - {ep_title}"
    return label


def _movie_label(movie: dict[str, Any]) -> str:
    """Build a human-readable label from a Radarr movie record."""
    title = movie.get("title", "Unknown Movie")
    year = movie.get("year")
    if year:
        return f"{title} ({year})"
    return title


def _group_by_season(records: list[dict]) -> dict[tuple[int, int], list[dict]]:
    """Group Sonarr records by (seriesId, seasonNumber) for season pack detection."""
    groups: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for record in records:
        series_id = record.get("seriesId")
        season = record.get("seasonNumber")
        if series_id is not None and season is not None and season > 0:
            groups[(series_id, season)].append(record)
    return dict(groups)


class SearchQueueError(Exception):
    """Base exception for search queue errors."""

    pass


class SearchQueueManager:
    """
    Manager for search queue operations and execution.

    Handles:
    - Queue lifecycle management
    - Search strategy execution
    - Rate limit enforcement
    - DB-backed tiered cooldown via LibraryItem
    - Priority scoring and batch truncation
    - Search history recording
    - Error handling and recovery
    """

    def __init__(self, db_session_factory: Callable[[], Session]):
        """
        Initialize search queue manager.

        Args:
            db_session_factory: Factory function to create database sessions
        """
        self.db_session_factory = db_session_factory
        self._rate_limit_tokens: dict[int, float] = {}  # instance_id -> tokens
        self._rate_limit_last_update: dict[int, datetime] = {}  # instance_id -> last_update

        logger.info("search_queue_manager_initialized")

    async def execute_queue(
        self, queue_id: int, override_cooldowns: bool = False
    ) -> dict[str, Any]:
        """
        Execute a search queue.

        Args:
            queue_id: ID of the search queue to execute
            override_cooldowns: If True, skip cooldown checks for this run

        Returns:
            dict: Execution results with keys:
                - status: "success" | "partial_success" | "failed"
                - items_searched: int
                - items_found: int
                - searches_triggered: int
                - errors: list[str]

        Raises:
            SearchQueueError: If queue doesn't exist or execution fails
        """
        db = self.db_session_factory()

        try:
            # Get queue and instance
            queue = db.query(SearchQueue).filter(SearchQueue.id == queue_id).first()

            if not queue:
                raise SearchQueueError(f"Search queue {queue_id} not found")

            if not queue.is_active:
                raise SearchQueueError(f"Search queue {queue_id} is not active")

            instance = db.query(Instance).filter(Instance.id == queue.instance_id).first()

            if not instance:
                raise SearchQueueError(f"Instance {queue.instance_id} not found")

            # Mark queue as in progress
            queue.mark_in_progress()
            db.commit()

            # Create history record
            history = SearchHistory.create_for_search(
                instance_id=instance.id,
                search_queue_id=queue.id,
                search_name=queue.name,
                strategy=queue.strategy,
            )
            db.add(history)
            db.commit()

            logger.info(
                "search_queue_execution_started",
                queue_id=queue_id,
                strategy=queue.strategy,
                instance_id=instance.id,
            )
            await event_bus.emit("search.started", {
                "queue_id": queue_id,
                "queue_name": queue.name,
                "strategy": queue.strategy,
                "max_items": queue.max_items_per_run,
            })

            # Resolve effective rate limit from Prowlarr (if configured)
            from splintarr.services.indexer_rate_limit import IndexerRateLimitService

            rate_service = IndexerRateLimitService(db)
            rate_result = await rate_service.get_effective_limit(
                instance_id=instance.id,
                user_id=instance.user_id,
                instance_rate=instance.rate_limit_per_second or 5.0,
                instance_url=instance.url,
            )
            if rate_result["max_items"] is not None:
                budget_aware = getattr(queue, "budget_aware", True)
                if budget_aware:
                    effective_max = min(queue.max_items_per_run or 50, rate_result["max_items"])
                    logger.debug(
                        "search_queue_budget_aware_applied",
                        queue_id=queue_id,
                        queue_max=queue.max_items_per_run,
                        prowlarr_budget=rate_result["max_items"],
                        effective_max=effective_max,
                    )
                else:
                    effective_max = queue.max_items_per_run or 50
                    logger.debug(
                        "search_queue_budget_aware_disabled",
                        queue_id=queue_id,
                        queue_max=queue.max_items_per_run,
                        prowlarr_budget=rate_result["max_items"],
                    )
                if effective_max == 0:
                    logger.warning(
                        "search_queue_prowlarr_budget_exhausted",
                        queue_id=queue_id,
                        instance_id=instance.id,
                        prowlarr_budget=rate_result["max_items"],
                        queue_max=queue.max_items_per_run,
                    )

                    # Early return: no budget remaining, skip strategy execution
                    skipped_result = {
                        "status": "skipped",
                        "items_searched": 0,
                        "items_found": 0,
                        "searches_triggered": 0,
                        "errors": [],
                        "search_log": [],
                    }

                    queue.mark_completed(items_found=0, items_searched=0)
                    history.mark_completed(
                        status="skipped",
                        items_searched=0,
                        items_found=0,
                        searches_triggered=0,
                        errors_encountered=0,
                        search_metadata=None,
                    )
                    db.commit()

                    return skipped_result
                else:
                    logger.info(
                        "search_queue_rate_limit_applied",
                        queue_id=queue_id,
                        instance_id=instance.id,
                        prowlarr_budget=rate_result["max_items"],
                        queue_max=queue.max_items_per_run,
                        effective_max=effective_max,
                    )
            else:
                effective_max = queue.max_items_per_run or 50

            try:
                # Execute based on strategy
                result = await self._execute_strategy(
                    queue,
                    instance,
                    db,
                    effective_max_items=effective_max,
                    override_cooldowns=override_cooldowns,
                )

                # Update queue and history with results
                queue.mark_completed(
                    items_found=result["items_found"],
                    items_searched=result["items_searched"],
                )

                # Serialize per-item search log into metadata
                search_log = result.get("search_log", [])
                metadata_json = json.dumps(search_log) if search_log else None

                history.mark_completed(
                    status=result["status"],
                    items_searched=result["items_searched"],
                    items_found=result["items_found"],
                    searches_triggered=result["searches_triggered"],
                    errors_encountered=len(result.get("errors", [])),
                    search_metadata=metadata_json,
                )

                db.commit()

                logger.info(
                    "search_queue_execution_completed",
                    queue_id=queue_id,
                    status=result["status"],
                    items_searched=result["items_searched"],
                    items_found=result["items_found"],
                )
                await event_bus.emit("search.completed", {
                    "queue_id": queue_id,
                    "queue_name": queue.name,
                    "status": result["status"],
                    "items_searched": result["items_searched"],
                    "items_found": result["items_found"],
                })
                await event_bus.emit("stats.updated", {})
                await event_bus.emit("activity.updated", {})

                # Fire-and-forget: send Discord notification for search results
                await self._notify_search_summary(
                    db=db,
                    user_id=instance.user_id,
                    search_name=queue.name,
                    instance_name=instance.name,
                    strategy=queue.strategy,
                    items_searched=result["items_searched"],
                    items_found=result["items_found"],
                    duration_seconds=0.0,  # duration not tracked yet
                )

                # Schedule feedback check to detect grabs after delay
                if result.get("searches_triggered", 0) > 0:
                    try:
                        from splintarr.services.scheduler import get_scheduler

                        scheduler = get_scheduler(self.db_session_factory)
                        scheduler.scheduler.add_job(
                            scheduler._execute_feedback_check,
                            trigger="date",
                            run_date=datetime.utcnow()
                            + timedelta(minutes=settings.feedback_check_delay_minutes),
                            id=f"feedback_check_{history.id}",
                            args=[history.id, instance.id],
                            replace_existing=True,
                        )
                        logger.info(
                            "feedback_check_scheduled",
                            history_id=history.id,
                            instance_id=instance.id,
                            delay_minutes=settings.feedback_check_delay_minutes,
                        )
                    except Exception as e:
                        logger.warning("feedback_check_schedule_failed", error=str(e))

                return result

            except Exception as e:
                # Mark queue and history as failed
                error_msg = str(e)
                queue.mark_failed(error_msg)
                history.mark_failed(error_msg)
                db.commit()

                logger.error("search_queue_execution_failed", queue_id=queue_id, error=error_msg)
                await event_bus.emit("search.failed", {
                    "queue_id": queue_id,
                    "error": str(e),
                })

                # Fire-and-forget: send Discord notification on failure
                await self._notify_queue_failed(
                    db=db,
                    user_id=instance.user_id,
                    queue_name=queue.name,
                    instance_name=instance.name,
                    error=error_msg,
                    consecutive_failures=queue.consecutive_failures
                    if hasattr(queue, "consecutive_failures")
                    else 1,
                )

                return {
                    "status": "failed",
                    "items_searched": 0,
                    "items_found": 0,
                    "searches_triggered": 0,
                    "errors": [error_msg],
                }

        finally:
            db.close()

    async def _execute_strategy(
        self,
        queue: SearchQueue,
        instance: Instance,
        db: Session,
        effective_max_items: int | None = None,
        override_cooldowns: bool = False,
    ) -> dict[str, Any]:
        """
        Execute search based on queue strategy.

        Args:
            queue: Search queue to execute
            instance: Instance to search on
            db: Database session
            effective_max_items: Override for max items per run (from Prowlarr budget)
            override_cooldowns: If True, skip cooldown checks for this run

        Returns:
            dict: Execution results
        """
        if queue.strategy == "missing":
            return await self._execute_missing_strategy(
                queue,
                instance,
                db,
                effective_max_items=effective_max_items,
                override_cooldowns=override_cooldowns,
            )
        elif queue.strategy == "cutoff_unmet":
            return await self._execute_cutoff_strategy(
                queue,
                instance,
                db,
                effective_max_items=effective_max_items,
                override_cooldowns=override_cooldowns,
            )
        elif queue.strategy == "recent":
            return await self._execute_recent_strategy(
                queue,
                instance,
                db,
                effective_max_items=effective_max_items,
                override_cooldowns=override_cooldowns,
            )
        elif queue.strategy == "custom":
            return await self._execute_custom_strategy(
                queue,
                instance,
                db,
                effective_max_items=effective_max_items,
                override_cooldowns=override_cooldowns,
            )
        else:
            raise SearchQueueError(f"Unknown strategy: {queue.strategy}")

    # ------------------------------------------------------------------
    # Fetch helpers
    # ------------------------------------------------------------------

    async def _fetch_all_records(
        self,
        client: Any,
        fetch_method: str,
        sort_key: str | None = None,
        sort_dir: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all wanted records across all pages.

        Args:
            client: Sonarr or Radarr client instance
            fetch_method: Name of the client method that returns paginated records
            sort_key: Optional sort key passed to the fetch method
            sort_dir: Optional sort direction passed to the fetch method

        Returns:
            list: All records across all pages
        """
        all_records: list[dict[str, Any]] = []
        page = 1
        fetch_fn = getattr(client, fetch_method)

        while True:
            fetch_kwargs: dict[str, Any] = {
                "page": page,
                "page_size": 50,
            }
            if sort_key:
                fetch_kwargs["sort_key"] = sort_key
            if sort_dir:
                fetch_kwargs["sort_dir"] = sort_dir

            result = await fetch_fn(**fetch_kwargs)
            records = result.get("records", [])
            if not records:
                break

            all_records.extend(records)
            total = result.get("totalRecords", 0)
            if len(all_records) >= total:
                break
            page += 1

        return all_records

    def _load_library_items(self, db: Session, instance_id: int) -> dict[int, Any]:
        """Load all LibraryItem records for an instance, keyed by external_id.

        Args:
            db: Database session
            instance_id: Instance to load library items for

        Returns:
            dict: Mapping of external_id -> LibraryItem
        """
        from splintarr.models.library import LibraryItem

        items = db.query(LibraryItem).filter(LibraryItem.instance_id == instance_id).all()
        return {item.external_id: item for item in items}

    # ------------------------------------------------------------------
    # Core search loop
    # ------------------------------------------------------------------

    async def _search_paginated_records(
        self,
        queue: SearchQueue,
        instance: Instance,
        db: Session,
        fetch_method: str | None,
        strategy_name: str,
        sort_key: str | None = None,
        sort_dir: str | None = None,
        effective_max_items: int | None = None,
        override_cooldowns: bool = False,
        prefetched_records: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Shared search loop for all strategies.

        New flow:
        1. Fetch ALL pages into a flat list (or use prefetched_records)
        2. Batch-load LibraryItem data from DB (keyed by external_id)
        3. Score each item using compute_score()
        4. Sort by score descending
        5. Filter: remove excluded items
        6. Filter: remove items in cooldown (using DB-backed cooldown)
           - Skipped when override_cooldowns is True
        7. Truncate to effective_max_items (Prowlarr-aware) or queue.max_items_per_run
        8. Search each remaining item, updating LibraryItem.search_attempts

        Args:
            queue: Search queue being executed (provides cooldown/batch config)
            instance: Instance to search on
            db: Database session for library item lookups
            fetch_method: Name of the client method that returns paginated records.
                Can be None when prefetched_records is provided.
            strategy_name: Used for log events (e.g. "missing", "cutoff", "custom")
            sort_key: Optional sort key passed to the fetch method
            sort_dir: Optional sort direction passed to the fetch method
            effective_max_items: Override for max items per run (from Prowlarr budget).
                If None, falls back to queue.max_items_per_run.
            override_cooldowns: If True, skip cooldown checks for this run.
            prefetched_records: Pre-fetched and pre-filtered records to use instead
                of calling the API. When provided, fetch_method is ignored.
        """
        logger.info(
            "executing_strategy",
            strategy=strategy_name,
            instance_type=instance.instance_type,
        )

        items_evaluated = 0  # total records from API (before filtering)
        items_searched = 0  # items that passed filtering and were searched
        items_found = 0
        searches_triggered = 0
        errors: list[str] = []
        search_log: list[dict[str, Any]] = []

        is_sonarr = instance.instance_type == "sonarr"
        item_type = "episode" if is_sonarr else "movie"
        content_type = "series" if is_sonarr else "movie"
        action_name = "EpisodeSearch" if is_sonarr else "MoviesSearch"

        # Load exclusion keys for this instance
        exclusion_service = ExclusionService(self.db_session_factory)
        excluded_keys = exclusion_service.get_active_exclusion_keys(
            user_id=instance.user_id,
            instance_id=instance.id,
        )

        # Queue configuration
        cooldown_mode = getattr(queue, "cooldown_mode", "adaptive") or "adaptive"
        cooldown_hours = getattr(queue, "cooldown_hours", None)
        max_items = (
            effective_max_items
            if effective_max_items is not None
            else (getattr(queue, "max_items_per_run", 50) or 50)
        )

        try:
            api_key = decrypt_api_key(instance.api_key)

            client_cls = SonarrClient if is_sonarr else RadarrClient
            async with client_cls(
                url=instance.url,
                api_key=api_key,
                verify_ssl=instance.verify_ssl,
                rate_limit_per_second=instance.rate_limit_per_second or 5,
            ) as client:
                search_fn = client.search_episodes if is_sonarr else client.search_movies

                # Step 1: Fetch all records (or use prefetched)
                if prefetched_records is not None:
                    all_records = prefetched_records
                    items_evaluated = len(all_records)
                    logger.info(
                        "prefetched_records_used",
                        strategy=strategy_name,
                        total_records=items_evaluated,
                        instance_id=instance.id,
                    )
                else:
                    all_records = await self._fetch_all_records(
                        client, fetch_method, sort_key=sort_key, sort_dir=sort_dir
                    )
                    items_evaluated = len(all_records)
                    logger.info(
                        "records_fetched",
                        strategy=strategy_name,
                        total_records=items_evaluated,
                        instance_id=instance.id,
                    )

                # Step 2: Batch-load library items
                library_items = self._load_library_items(db, instance.id)

                # Build label function with library fallback for series titles
                if is_sonarr:

                    def label_fn(rec: dict[str, Any]) -> str:
                        return _episode_label(rec, library_items=library_items)
                else:
                    label_fn = _movie_label

                # Load per-episode search tracking (Sonarr only)
                episode_tracking: dict[tuple[int, int, int], Any] = {}
                if is_sonarr and library_items:
                    from splintarr.models.library import LibraryEpisode

                    item_ids = [li.id for li in library_items.values()]
                    if item_ids:
                        db_episodes = (
                            db.query(LibraryEpisode)
                            .filter(LibraryEpisode.library_item_id.in_(item_ids))
                            .all()
                        )
                        for ep in db_episodes:
                            if ep.library_item:
                                episode_tracking[
                                    (
                                        ep.library_item.external_id,
                                        ep.season_number,
                                        ep.episode_number,
                                    )
                                ] = ep

                # Step 3-7: Score, sort, filter, truncate
                scored_records: list[tuple[dict[str, Any], float, str]] = []
                for record in all_records:
                    item_id = record.get("id")
                    if not item_id:
                        continue

                    # Determine library-level external ID
                    if is_sonarr:
                        ext_id = record.get("seriesId") or record.get("series", {}).get("id")
                    else:
                        ext_id = item_id

                    # Step 5: Filter excluded items
                    if ext_id and (ext_id, content_type) in excluded_keys:
                        label = label_fn(record)
                        logger.debug(
                            "item_excluded",
                            item_type=item_type,
                            item_id=item_id,
                            external_id=ext_id,
                            content_type=content_type,
                        )
                        search_log.append(
                            {
                                "item": label,
                                "action": "skipped",
                                "reason": "excluded",
                            }
                        )
                        continue

                    # Step 6: Filter cooldown items (skip when overridden)
                    library_item = library_items.get(ext_id)
                    if not override_cooldowns and is_in_cooldown(
                        library_item, record, cooldown_mode, cooldown_hours
                    ):
                        label = label_fn(record)
                        logger.debug(
                            "item_in_cooldown",
                            item_type=item_type,
                            item_id=item_id,
                        )
                        search_log.append(
                            {
                                "item": label,
                                "action": "skipped",
                                "reason": "cooldown",
                            }
                        )
                        continue

                    # Step 3: Score each item
                    score, reason = compute_score(record, library_item, strategy_name)

                    # Per-episode deprioritization: penalize recently-searched episodes
                    if is_sonarr:
                        s_id = record.get("seriesId") or record.get("series", {}).get("id")
                        s_num = record.get("seasonNumber")
                        e_num = record.get("episodeNumber")
                        if s_id and s_num is not None and e_num is not None:
                            ep_rec = episode_tracking.get((s_id, s_num, e_num))
                            if ep_rec and ep_rec.last_searched_at:
                                hours = (
                                    datetime.utcnow() - ep_rec.last_searched_at
                                ).total_seconds() / 3600
                                if hours < 24:
                                    penalty = 50.0 * (1.0 - hours / 24.0)
                                    score = max(0, score - penalty)
                                    reason += f" (ep searched {hours:.0f}h ago: -{penalty:.0f})"

                    scored_records.append((record, score, reason))

                # Step 4: Sort by score descending
                scored_records.sort(key=lambda x: x[1], reverse=True)

                # Step 7: Truncate to max_items_per_run
                truncated = scored_records[:max_items]

                batch_total = len(truncated)
                logger.info(
                    "search_batch_prepared",
                    strategy=strategy_name,
                    scored_count=len(scored_records),
                    batch_size=batch_total,
                    max_items=max_items,
                )

                # Step 7.5: Season pack grouping (Sonarr only)
                season_pack_enabled = getattr(queue, "season_pack_enabled", False) and is_sonarr

                if season_pack_enabled:
                    threshold = getattr(queue, "season_pack_threshold", 3) or 3
                    truncated_records = [rec for rec, _score, _reason in truncated]
                    season_groups = _group_by_season(truncated_records)

                    for (sid, snum), group_records in season_groups.items():
                        if len(group_records) >= threshold:
                            # Step 8a: Issue season pack search
                            if not await self._check_rate_limit(instance.id):
                                logger.warning(
                                    "rate_limit_reached",
                                    instance_id=instance.id,
                                )
                                break

                            try:
                                cmd_result = await client.season_search(
                                    series_id=sid, season_number=snum
                                )
                                searches_triggered += 1
                                items_found += 1

                                # Count episodes covered by the pack search
                                for rec in group_records:
                                    if rec.get("id") is not None:
                                        items_searched += 1

                                # Update LibraryItem search tracking for the series
                                library_item = library_items.get(sid)
                                if library_item:
                                    library_item.record_search()

                                logger.info(
                                    "season_pack_search_triggered",
                                    series_id=sid,
                                    season_number=snum,
                                    episode_count=len(group_records),
                                    instance_id=instance.id,
                                    command_id=cmd_result.get("id"),
                                )

                                # Log each episode covered by the pack search
                                for rec in group_records:
                                    label = label_fn(rec)
                                    search_log.append(
                                        {
                                            "item": label,
                                            "action": "SeasonSearch",
                                            "series_id": sid,
                                            "season_number": snum,
                                            "item_id": rec.get("id"),
                                            "command_id": cmd_result.get("id"),
                                            "result": "sent",
                                            "season_pack": True,
                                        }
                                    )
                            except Exception as e:
                                errors.append(f"SeasonSearch series={sid} S{snum:02d}: {e}")
                                logger.error(
                                    "season_pack_search_failed",
                                    series_id=sid,
                                    season_number=snum,
                                    error=str(e),
                                    instance_id=instance.id,
                                )

                # Step 8: Search each item individually
                # Season pack search above is an optimization; individual
                # search serves as fallback if the pack didn't grab.
                for batch_idx, (record, score, reason) in enumerate(truncated, start=1):
                    item_id = record.get("id")

                    label = label_fn(record)

                    # Determine external IDs for log and library item lookup
                    if is_sonarr:
                        series_id = record.get("seriesId") or record.get("series", {}).get("id")
                        ext_id = series_id
                    else:
                        series_id = None
                        ext_id = item_id

                    items_searched += 1

                    if not await self._check_rate_limit(instance.id):
                        logger.warning(
                            "rate_limit_reached",
                            instance_id=instance.id,
                        )
                        search_log.append(
                            {
                                "item": label,
                                "action": "skipped",
                                "reason": "rate_limit",
                                "score": score,
                                "score_reason": reason,
                            }
                        )
                        break

                    try:
                        cmd_result = await search_fn([item_id])
                        items_found += 1
                        searches_triggered += 1

                        # Update LibraryItem search tracking
                        library_item = library_items.get(ext_id)
                        if library_item:
                            library_item.record_search()

                        # Update per-episode search tracking
                        if is_sonarr:
                            s_id = record.get("seriesId") or record.get("series", {}).get("id")
                            s_num = record.get("seasonNumber")
                            e_num = record.get("episodeNumber")
                            ep_rec = episode_tracking.get((s_id, s_num, e_num) if s_id else ())
                            if ep_rec:
                                ep_rec.record_search()

                        logger.debug(
                            "item_search_triggered",
                            item_type=item_type,
                            item_id=item_id,
                            score=score,
                            score_reason=reason,
                        )
                        search_log.append(
                            {
                                "item": label,
                                "action": action_name,
                                "score": score,
                                "score_reason": reason,
                                "item_id": item_id,
                                "series_id": series_id,
                                "command_id": cmd_result.get("id"),
                                "result": "sent",
                            }
                        )
                        await event_bus.emit("search.item_result", {
                            "queue_id": queue.id,
                            "item_name": label,
                            "result": "found",
                            "score": score,
                            "score_reason": reason,
                            "item_index": batch_idx,
                            "total_items": batch_total,
                        })
                    except Exception as e:
                        errors.append(f"{item_type.title()} {item_id}: {e}")
                        logger.error(
                            "item_search_failed",
                            item_type=item_type,
                            item_id=item_id,
                            error=str(e),
                        )
                        search_log.append(
                            {
                                "item": label,
                                "action": action_name,
                                "score": score,
                                "score_reason": reason,
                                "item_id": item_id,
                                "series_id": series_id,
                                "result": "error",
                                "error": str(e),
                            }
                        )
                        await event_bus.emit("search.item_result", {
                            "queue_id": queue.id,
                            "item_name": label,
                            "result": "failed",
                            "score": score,
                            "score_reason": reason,
                            "item_index": batch_idx,
                            "total_items": batch_total,
                        })

                # Commit library item search tracking updates
                try:
                    db.commit()
                except Exception as e:
                    logger.warning(
                        "library_item_search_tracking_commit_failed",
                        error=str(e),
                    )

            if errors:
                result_status = "partial_success" if items_found > 0 else "failed"
            else:
                result_status = "success"

            return {
                "status": result_status,
                "items_evaluated": items_evaluated,
                "items_searched": items_searched,
                "items_found": items_found,
                "searches_triggered": searches_triggered,
                "errors": errors,
                "search_log": search_log,
            }

        except Exception as e:
            logger.error(
                "strategy_execution_failed",
                strategy=strategy_name,
                error=str(e),
            )
            raise

    async def _execute_missing_strategy(
        self,
        queue: SearchQueue,
        instance: Instance,
        db: Session,
        effective_max_items: int | None = None,
        override_cooldowns: bool = False,
    ) -> dict[str, Any]:
        """Execute missing items strategy -- searches all missing episodes/movies."""
        return await self._search_paginated_records(
            queue=queue,
            instance=instance,
            db=db,
            fetch_method="get_wanted_missing",
            strategy_name="missing",
            effective_max_items=effective_max_items,
            override_cooldowns=override_cooldowns,
        )

    async def _execute_cutoff_strategy(
        self,
        queue: SearchQueue,
        instance: Instance,
        db: Session,
        effective_max_items: int | None = None,
        override_cooldowns: bool = False,
    ) -> dict[str, Any]:
        """Execute cutoff unmet strategy -- searches items below quality cutoff."""
        return await self._search_paginated_records(
            queue=queue,
            instance=instance,
            db=db,
            fetch_method="get_wanted_cutoff",
            strategy_name="cutoff",
            effective_max_items=effective_max_items,
            override_cooldowns=override_cooldowns,
        )

    async def _execute_recent_strategy(
        self,
        queue: SearchQueue,
        instance: Instance,
        db: Session,
        effective_max_items: int | None = None,
        override_cooldowns: bool = False,
    ) -> dict[str, Any]:
        """Execute recent additions strategy -- newest missing items first."""
        if instance.instance_type == "sonarr":
            sort_key, sort_dir = "airDateUtc", "descending"
        else:
            sort_key, sort_dir = "added", "descending"

        return await self._search_paginated_records(
            queue=queue,
            instance=instance,
            db=db,
            fetch_method="get_wanted_missing",
            strategy_name="recent",
            sort_key=sort_key,
            sort_dir=sort_dir,
            effective_max_items=effective_max_items,
            override_cooldowns=override_cooldowns,
        )

    async def _execute_custom_strategy(
        self,
        queue: SearchQueue,
        instance: Instance,
        db: Session,
        effective_max_items: int | None = None,
        override_cooldowns: bool = False,
    ) -> dict[str, Any]:
        """Execute custom strategy with user-defined filters.

        Fetches records from one or more sources (missing, cutoff_unmet),
        deduplicates them, applies custom filters via apply_custom_filters(),
        then feeds the filtered records into the standard scoring/search pipeline.

        Args:
            queue: Search queue with filters JSON
            instance: Instance to search on
            db: Database session
            effective_max_items: Override for max items per run (from Prowlarr budget)
            override_cooldowns: If True, skip cooldown checks for this run

        Returns:
            dict: Execution results
        """
        logger.info(
            "executing_custom_strategy",
            instance_type=instance.instance_type,
            queue_id=queue.id,
            instance_id=instance.id,
        )

        # Parse custom filters
        filters: dict[str, Any] = {}
        if queue.filters:
            try:
                filters = json.loads(queue.filters)
            except json.JSONDecodeError as err:
                raise SearchQueueError("Invalid custom filters JSON") from err

        sources: list[str] = filters.get("sources", ["missing"])

        # Fetch from all configured sources
        api_key = decrypt_api_key(instance.api_key)
        is_sonarr = instance.instance_type == "sonarr"
        client_cls = SonarrClient if is_sonarr else RadarrClient

        all_records: list[dict[str, Any]] = []
        seen_keys: set[tuple[int, int]] = set()

        async with client_cls(
            url=instance.url,
            api_key=api_key,
            verify_ssl=instance.verify_ssl,
            rate_limit_per_second=instance.rate_limit_per_second or 5,
        ) as client:
            for source in sources:
                fetch_method = (
                    "get_wanted_missing"
                    if source == "missing"
                    else "get_wanted_cutoff"
                )
                records = await self._fetch_all_records(client, fetch_method)
                for record in records:
                    series_id = (
                        record.get("seriesId")
                        or record.get("series", {}).get("id", 0)
                    )
                    record_id = record.get("id", 0)
                    key = (series_id, record_id)
                    if key not in seen_keys:
                        seen_keys.add(key)
                        all_records.append(record)

        logger.info(
            "custom_strategy_records_fetched",
            sources=sources,
            total_records=len(all_records),
            queue_id=queue.id,
            instance_id=instance.id,
        )

        # Load library items for filtering
        library_items = self._load_library_items(db, instance.id)

        # Apply custom filters
        filtered_records = apply_custom_filters(all_records, library_items, filters)

        logger.info(
            "custom_strategy_filters_applied",
            total=len(all_records),
            after_filters=len(filtered_records),
            queue_id=queue.id,
            instance_id=instance.id,
        )

        # Feed into the standard pipeline with prefetched records
        return await self._search_paginated_records(
            queue=queue,
            instance=instance,
            db=db,
            fetch_method=None,
            strategy_name="custom",
            sort_key=None,
            sort_dir=None,
            effective_max_items=effective_max_items,
            override_cooldowns=override_cooldowns,
            prefetched_records=filtered_records,
        )

    _STRATEGY_PARAMS: dict[str, tuple[str, str, str | None, str | None]] = {
        "missing": ("get_wanted_missing", "missing", None, None),
        "cutoff_unmet": ("get_wanted_cutoff", "cutoff", None, None),
        "custom": ("get_wanted_missing", "missing", None, None),
    }

    def _get_strategy_params(
        self, queue: SearchQueue, instance: Instance
    ) -> tuple[str, str, str | None, str | None]:
        """Return (fetch_method, strategy_name, sort_key, sort_dir) for a queue's strategy."""
        if queue.strategy == "recent":
            sort_key = "airDateUtc" if instance.instance_type == "sonarr" else "added"
            return ("get_wanted_missing", "recent", sort_key, "descending")

        params = self._STRATEGY_PARAMS.get(queue.strategy)
        if params is None:
            raise SearchQueueError(f"Unknown strategy: {queue.strategy}")
        return params

    async def preview_queue(
        self, queue_id: int
    ) -> dict[str, Any]:
        """Run the scoring/filtering pipeline without executing searches.

        Returns the item list in priority order with scores, reasons,
        season pack groupings, and skip counts.
        """
        db = self.db_session_factory()
        try:
            queue = db.query(SearchQueue).filter(SearchQueue.id == queue_id).first()
            if not queue:
                raise SearchQueueError(f"Queue {queue_id} not found")
            if not queue.is_active:
                raise SearchQueueError(f"Queue {queue_id} is paused")

            instance = db.query(Instance).filter(Instance.id == queue.instance_id).first()
            if not instance:
                raise SearchQueueError("Instance not found")

            logger.info(
                "search_preview_started",
                queue_id=queue_id,
                strategy=queue.strategy,
                instance_id=instance.id,
            )

            fetch_method, strategy_name, sort_key, sort_dir = self._get_strategy_params(
                queue, instance
            )

            # Parse custom filters
            filters: dict[str, Any] = {}
            if queue.strategy == "custom" and queue.filters:
                try:
                    filters = json.loads(queue.filters)
                except json.JSONDecodeError as err:
                    raise SearchQueueError("Invalid custom filters JSON") from err

            is_sonarr = instance.instance_type == "sonarr"
            max_items = getattr(queue, "max_items_per_run", 50) or 50

            api_key = decrypt_api_key(instance.api_key)
            client_cls = SonarrClient if is_sonarr else RadarrClient

            if queue.strategy == "custom" and filters:
                # Multi-source fetch with dedup (same logic as _execute_custom_strategy)
                sources: list[str] = filters.get("sources", ["missing"])
                all_records: list[dict[str, Any]] = []
                seen_keys: set[tuple[int, int]] = set()

                async with client_cls(
                    url=instance.url,
                    api_key=api_key,
                    verify_ssl=instance.verify_ssl,
                    rate_limit_per_second=instance.rate_limit_per_second or 5,
                ) as client:
                    for source in sources:
                        source_fetch = (
                            "get_wanted_missing"
                            if source == "missing"
                            else "get_wanted_cutoff"
                        )
                        records = await self._fetch_all_records(client, source_fetch)
                        for record in records:
                            series_id = (
                                record.get("seriesId")
                                or record.get("series", {}).get("id", 0)
                            )
                            record_id = record.get("id", 0)
                            key = (series_id, record_id)
                            if key not in seen_keys:
                                seen_keys.add(key)
                                all_records.append(record)
            else:
                async with client_cls(
                    url=instance.url,
                    api_key=api_key,
                    verify_ssl=instance.verify_ssl,
                    rate_limit_per_second=instance.rate_limit_per_second or 5,
                ) as client:
                    all_records = await self._fetch_all_records(
                        client, fetch_method, sort_key=sort_key, sort_dir=sort_dir
                    )

            # Load library data and exclusions
            library_items = self._load_library_items(db, instance.id)
            exclusion_service = ExclusionService(self.db_session_factory)
            excluded_keys = exclusion_service.get_active_exclusion_keys(
                user_id=instance.user_id, instance_id=instance.id
            )

            # Apply custom filters (for custom strategy)
            if queue.strategy == "custom" and filters:
                all_records = apply_custom_filters(all_records, library_items, filters)

            content_type = "series" if is_sonarr else "movie"
            cooldown_mode = getattr(queue, "cooldown_mode", "adaptive") or "adaptive"
            cooldown_hours = getattr(queue, "cooldown_hours", None)

            # Build label function
            if is_sonarr:
                def label_fn(rec: dict[str, Any]) -> str:
                    return _episode_label(rec, library_items=library_items)
            else:
                label_fn = _movie_label

            # Load per-episode tracking (Sonarr)
            episode_tracking: dict[tuple[int, int, int], Any] = {}
            if is_sonarr and library_items:
                from splintarr.models.library import LibraryEpisode

                item_ids = [li.id for li in library_items.values()]
                if item_ids:
                    db_episodes = (
                        db.query(LibraryEpisode)
                        .filter(LibraryEpisode.library_item_id.in_(item_ids))
                        .all()
                    )
                    for ep in db_episodes:
                        if ep.library_item:
                            episode_tracking[
                                (ep.library_item.external_id, ep.season_number, ep.episode_number)
                            ] = ep

            # Score, filter, sort — same pipeline as _search_paginated_records Steps 3-7
            scored_records: list[tuple[dict[str, Any], float, str]] = []
            excluded_count = 0
            cooldown_count = 0

            for record in all_records:
                item_id = record.get("id")
                if not item_id:
                    continue

                ext_id = (
                    record.get("seriesId") or record.get("series", {}).get("id")
                    if is_sonarr
                    else item_id
                )

                if ext_id and (ext_id, content_type) in excluded_keys:
                    excluded_count += 1
                    continue

                library_item = library_items.get(ext_id)
                if is_in_cooldown(library_item, record, cooldown_mode, cooldown_hours):
                    cooldown_count += 1
                    continue

                score, reason = compute_score(record, library_item, strategy_name)

                # Per-episode deprioritization
                if is_sonarr:
                    s_id = record.get("seriesId") or record.get("series", {}).get("id")
                    s_num = record.get("seasonNumber")
                    e_num = record.get("episodeNumber")
                    if s_id and s_num is not None and e_num is not None:
                        ep_rec = episode_tracking.get((s_id, s_num, e_num))
                        if ep_rec and ep_rec.last_searched_at:
                            hours_since = (
                                datetime.now(UTC) - ep_rec.last_searched_at.replace(tzinfo=UTC)
                            ).total_seconds() / 3600
                            if hours_since < 24:
                                penalty = 50.0 * (1.0 - hours_since / 24.0)
                                score = max(0, score - penalty)
                                reason += f" (ep searched {hours_since:.0f}h ago: -{penalty:.0f})"

                scored_records.append((record, score, reason))

            scored_records.sort(key=lambda x: x[1], reverse=True)
            truncated = scored_records[:max_items]

            # Build preview items
            items = []
            for record, score, reason in truncated:
                label = label_fn(record)
                items.append({
                    "item": label,
                    "score": round(score, 1),
                    "score_reason": reason,
                })

            # Season pack groupings (Sonarr only)
            season_packs: list[dict[str, Any]] = []
            season_pack_enabled = getattr(queue, "season_pack_enabled", False) and is_sonarr
            if season_pack_enabled:
                threshold = getattr(queue, "season_pack_threshold", 3) or 3
                truncated_records = [rec for rec, _s, _r in truncated]
                groups = _group_by_season(truncated_records)
                for (series_id, season_num), episodes in groups.items():
                    if len(episodes) >= threshold:
                        first = episodes[0]
                        series_title = first.get("series", {}).get("title", f"Series {series_id}")
                        season_packs.append({
                            "series": series_title,
                            "season": season_num,
                            "episodes": len(episodes),
                        })

            logger.info(
                "search_preview_completed",
                queue_id=queue_id,
                total_records=len(all_records),
                excluded=excluded_count,
                cooldown=cooldown_count,
                scored=len(scored_records),
                batch_size=len(truncated),
                season_packs=len(season_packs),
            )

            return {
                "queue_id": queue_id,
                "strategy": strategy_name,
                "total_eligible": len(all_records),
                "excluded_count": excluded_count,
                "cooldown_count": cooldown_count,
                "scored_count": len(scored_records),
                "batch_size": len(truncated),
                "max_items": max_items,
                "items": items,
                "season_packs": season_packs,
            }
        finally:
            db.close()

    async def _check_rate_limit(self, instance_id: int, tokens_per_second: float = 5.0) -> bool:
        """
        Check if rate limit allows a new request (token bucket algorithm).

        Args:
            instance_id: Instance ID
            tokens_per_second: Rate limit in tokens per second (default: 5.0)

        Returns:
            bool: True if request is allowed
        """
        now = datetime.utcnow()

        # Initialize if first request
        if instance_id not in self._rate_limit_tokens:
            self._rate_limit_tokens[instance_id] = tokens_per_second
            self._rate_limit_last_update[instance_id] = now
            return True

        # Calculate tokens to add since last update
        time_passed = (now - self._rate_limit_last_update[instance_id]).total_seconds()
        tokens_to_add = time_passed * tokens_per_second

        # Update tokens (cap at max)
        self._rate_limit_tokens[instance_id] = min(
            tokens_per_second,
            self._rate_limit_tokens[instance_id] + tokens_to_add,
        )
        self._rate_limit_last_update[instance_id] = now

        # Check if we have a token available
        if self._rate_limit_tokens[instance_id] >= 1.0:
            self._rate_limit_tokens[instance_id] -= 1.0
            return True

        return False

    # ------------------------------------------------------------------
    # Discord notification helpers (fire-and-forget)
    # ------------------------------------------------------------------

    async def _notify_search_summary(
        self,
        db: Session,
        user_id: int,
        search_name: str,
        instance_name: str,
        strategy: str,
        items_searched: int,
        items_found: int,
        duration_seconds: float,
    ) -> None:
        """Send a search summary Discord notification if configured and enabled."""
        try:
            config = (
                db.query(NotificationConfig)
                .filter(
                    NotificationConfig.user_id == user_id,
                    NotificationConfig.is_active.is_(True),
                )
                .first()
            )
            if not config or not config.is_event_enabled("search_triggered"):
                return

            webhook_url = decrypt_field(config.webhook_url)
            service = DiscordNotificationService(webhook_url)
            await service.send_search_summary(
                search_name=search_name,
                instance_name=instance_name,
                strategy=strategy,
                items_searched=items_searched,
                items_found=items_found,
                duration_seconds=duration_seconds,
            )
        except Exception as e:
            logger.warning(
                "discord_notification_send_failed",
                event="search_triggered",
                user_id=user_id,
                error=str(e),
            )

    async def _notify_queue_failed(
        self,
        db: Session,
        user_id: int,
        queue_name: str,
        instance_name: str,
        error: str,
        consecutive_failures: int,
    ) -> None:
        """Send a queue failure Discord notification if configured and enabled."""
        try:
            config = (
                db.query(NotificationConfig)
                .filter(
                    NotificationConfig.user_id == user_id,
                    NotificationConfig.is_active.is_(True),
                )
                .first()
            )
            if not config or not config.is_event_enabled("queue_failed"):
                return

            webhook_url = decrypt_field(config.webhook_url)
            service = DiscordNotificationService(webhook_url)
            await service.send_queue_failed(
                queue_name=queue_name,
                instance_name=instance_name,
                error=error,
                consecutive_failures=consecutive_failures,
            )
        except Exception as e:
            logger.warning(
                "discord_notification_send_failed",
                event="queue_failed",
                user_id=user_id,
                error=str(e),
            )
