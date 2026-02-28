"""
Search Queue Management Service for Splintarr.

This module implements search queue operations and execution:
- Queue CRUD operations (add, update, delete)
- Search strategy implementations (missing, cutoff, recent, custom)
- Priority calculation and item filtering
- Batch processing with rate limiting
- Integration with Sonarr/Radarr clients
- Search history tracking

The queue manager coordinates with the scheduler to execute automated searches
across configured instances.
"""

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy.orm import Session

from splintarr.core.security import decrypt_api_key, decrypt_field
from splintarr.models import Instance, NotificationConfig, SearchHistory, SearchQueue
from splintarr.services.discord import DiscordNotificationService
from splintarr.services.radarr import RadarrClient
from splintarr.services.sonarr import SonarrClient

logger = structlog.get_logger()


def _episode_label(episode: dict[str, Any]) -> str:
    """Build a human-readable label from a Sonarr episode record."""
    series = episode.get("series", {})
    series_title = series.get("title", "Unknown Series")
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
    - Cooldown period tracking
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
        self._search_cooldowns: dict[str, datetime] = {}  # item_key -> last_search_time
        self._rate_limit_tokens: dict[int, float] = {}  # instance_id -> tokens
        self._rate_limit_last_update: dict[int, datetime] = {}  # instance_id -> last_update

        logger.info("search_queue_manager_initialized")

    async def execute_queue(self, queue_id: int) -> dict[str, Any]:
        """
        Execute a search queue.

        Args:
            queue_id: ID of the search queue to execute

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

            try:
                # Execute based on strategy
                result = await self._execute_strategy(queue, instance, db)

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

                # Fire-and-forget: send Discord notification on successful search
                if result["items_found"] > 0:
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

                return result

            except Exception as e:
                # Mark queue and history as failed
                error_msg = str(e)
                queue.mark_failed(error_msg)
                history.mark_failed(error_msg)
                db.commit()

                logger.error("search_queue_execution_failed", queue_id=queue_id, error=error_msg)

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
    ) -> dict[str, Any]:
        """
        Execute search based on queue strategy.

        Args:
            queue: Search queue to execute
            instance: Instance to search on
            db: Database session

        Returns:
            dict: Execution results
        """
        if queue.strategy == "missing":
            return await self._execute_missing_strategy(queue, instance, db)
        elif queue.strategy == "cutoff_unmet":
            return await self._execute_cutoff_strategy(queue, instance, db)
        elif queue.strategy == "recent":
            return await self._execute_recent_strategy(queue, instance, db)
        elif queue.strategy == "custom":
            return await self._execute_custom_strategy(queue, instance, db)
        else:
            raise SearchQueueError(f"Unknown strategy: {queue.strategy}")

    async def _search_paginated_records(
        self,
        instance: Instance,
        fetch_method: str,
        strategy_name: str,
        paginate_all: bool = True,
        sort_key: str | None = None,
        sort_dir: str | None = None,
    ) -> dict[str, Any]:
        """Shared search loop for all strategies.

        Creates the appropriate client, fetches records via fetch_method
        (e.g. "get_wanted_missing"), and triggers per-item searches with
        cooldown and rate-limit enforcement.

        Args:
            instance: Instance to search on
            fetch_method: Name of the client method that returns paginated records
            strategy_name: Used for log events (e.g. "missing", "cutoff")
            paginate_all: If True, iterate all pages; if False, fetch only page 1
            sort_key: Optional sort key passed to the fetch method
            sort_dir: Optional sort direction passed to the fetch method
        """
        logger.info(
            "executing_strategy",
            strategy=strategy_name,
            instance_type=instance.instance_type,
        )

        items_searched = 0
        items_found = 0
        searches_triggered = 0
        errors: list[str] = []
        search_log: list[dict[str, Any]] = []

        is_sonarr = instance.instance_type == "sonarr"
        item_type = "episode" if is_sonarr else "movie"
        action_name = "EpisodeSearch" if is_sonarr else "MoviesSearch"

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
                label_fn = _episode_label if is_sonarr else _movie_label
                fetch_fn = getattr(client, fetch_method)

                page = 1
                rate_limited = False
                while not rate_limited:
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

                    for record in records:
                        item_id = record.get("id")
                        if not item_id:
                            continue

                        items_searched += 1
                        label = label_fn(record)
                        cooldown_key = (
                            f"{instance.instance_type}_{instance.id}_{item_type}_{item_id}"
                        )

                        if self._is_in_cooldown(cooldown_key):
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
                                }
                            )
                            rate_limited = True
                            break

                        try:
                            cmd_result = await search_fn([item_id])
                            items_found += 1
                            searches_triggered += 1
                            self._set_cooldown(cooldown_key)
                            logger.debug(
                                "item_search_triggered",
                                item_type=item_type,
                                item_id=item_id,
                            )
                            search_log.append(
                                {
                                    "item": label,
                                    "action": action_name,
                                    "command_id": cmd_result.get("id"),
                                    "result": "sent",
                                }
                            )
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
                                    "result": "error",
                                    "error": str(e),
                                }
                            )

                    if not paginate_all:
                        break
                    page += 1

            if errors:
                result_status = "partial_success" if items_found > 0 else "failed"
            else:
                result_status = "success"

            return {
                "status": result_status,
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
    ) -> dict[str, Any]:
        """Execute missing items strategy -- searches all missing episodes/movies."""
        return await self._search_paginated_records(
            instance,
            fetch_method="get_wanted_missing",
            strategy_name="missing",
        )

    async def _execute_cutoff_strategy(
        self,
        queue: SearchQueue,
        instance: Instance,
        db: Session,
    ) -> dict[str, Any]:
        """Execute cutoff unmet strategy -- searches items below quality cutoff."""
        return await self._search_paginated_records(
            instance,
            fetch_method="get_wanted_cutoff",
            strategy_name="cutoff",
        )

    async def _execute_recent_strategy(
        self,
        queue: SearchQueue,
        instance: Instance,
        db: Session,
    ) -> dict[str, Any]:
        """Execute recent additions strategy -- newest missing items first."""
        if instance.instance_type == "sonarr":
            sort_key, sort_dir = "airDateUtc", "descending"
        else:
            sort_key, sort_dir = "added", "descending"

        return await self._search_paginated_records(
            instance,
            fetch_method="get_wanted_missing",
            strategy_name="recent",
            paginate_all=False,
            sort_key=sort_key,
            sort_dir=sort_dir,
        )

    async def _execute_custom_strategy(
        self,
        queue: SearchQueue,
        instance: Instance,
        db: Session,
    ) -> dict[str, Any]:
        """
        Execute custom strategy with user-defined filters.

        Args:
            queue: Search queue
            instance: Instance to search on
            db: Database session

        Returns:
            dict: Execution results
        """
        logger.info("executing_custom_strategy", instance_type=instance.instance_type)

        # Parse custom filters
        filters = {}
        if queue.filters:
            try:
                filters = json.loads(queue.filters)
            except json.JSONDecodeError:
                raise SearchQueueError("Invalid custom filters JSON")

        # For now, custom strategy defaults to missing strategy
        # In a real implementation, you would apply the custom filters
        logger.warning("custom_strategy_using_missing_fallback", filters=filters)

        return await self._execute_missing_strategy(queue, instance, db)

    def _is_in_cooldown(self, item_key: str, cooldown_hours: int = 24) -> bool:
        """
        Check if an item is in cooldown period.

        Args:
            item_key: Unique key for the item
            cooldown_hours: Cooldown period in hours (default: 24)

        Returns:
            bool: True if item is in cooldown
        """
        if item_key not in self._search_cooldowns:
            return False

        last_search = self._search_cooldowns[item_key]
        cooldown_end = last_search + timedelta(hours=cooldown_hours)
        now = datetime.utcnow()

        if now >= cooldown_end:
            del self._search_cooldowns[item_key]
            return False

        return True

    def _set_cooldown(self, item_key: str) -> None:
        """
        Set cooldown for an item.

        Args:
            item_key: Unique key for the item
        """
        self._search_cooldowns[item_key] = datetime.utcnow()

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
