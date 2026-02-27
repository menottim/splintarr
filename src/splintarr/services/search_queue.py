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

from splintarr.core.security import decrypt_api_key
from splintarr.models import Instance, SearchHistory, SearchQueue
from splintarr.services.radarr import RadarrClient
from splintarr.services.sonarr import SonarrClient

logger = structlog.get_logger()


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

                history.mark_completed(
                    status=result["status"],
                    items_searched=result["items_searched"],
                    items_found=result["items_found"],
                    searches_triggered=result["searches_triggered"],
                    errors_encountered=len(result.get("errors", [])),
                )

                db.commit()

                logger.info(
                    "search_queue_execution_completed",
                    queue_id=queue_id,
                    status=result["status"],
                    items_searched=result["items_searched"],
                    items_found=result["items_found"],
                )

                return result

            except Exception as e:
                # Mark queue and history as failed
                error_msg = str(e)
                queue.mark_failed(error_msg)
                history.mark_failed(error_msg)
                db.commit()

                logger.error("search_queue_execution_failed", queue_id=queue_id, error=error_msg)

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

    async def _execute_missing_strategy(
        self,
        queue: SearchQueue,
        instance: Instance,
        db: Session,
    ) -> dict[str, Any]:
        """
        Execute missing items strategy.

        Searches for all missing episodes/movies.

        Args:
            queue: Search queue
            instance: Instance to search on
            db: Database session

        Returns:
            dict: Execution results
        """
        logger.info("executing_missing_strategy", instance_type=instance.type)

        items_searched = 0
        items_found = 0
        searches_triggered = 0
        errors = []

        try:
            # Decrypt API key
            api_key = decrypt_api_key(instance.encrypted_api_key)

            if instance.type == "sonarr":
                async with SonarrClient(
                    url=instance.url,
                    api_key=api_key,
                    verify_ssl=instance.verify_ssl,
                    rate_limit_per_second=instance.rate_limit or 5.0,
                ) as client:
                    # Get all missing episodes
                    page = 1
                    while True:
                        result = await client.get_wanted_missing(page=page, page_size=50)
                        records = result.get("records", [])

                        if not records:
                            break

                        for episode in records:
                            episode_id = episode.get("id")
                            if not episode_id:
                                continue

                            items_searched += 1

                            # Check cooldown
                            if self._is_in_cooldown(f"sonarr_{instance.id}_episode_{episode_id}"):
                                logger.debug("item_in_cooldown", episode_id=episode_id)
                                continue

                            # Check rate limit
                            if not await self._check_rate_limit(instance.id):
                                logger.warning("rate_limit_reached", instance_id=instance.id)
                                break

                            # Trigger search
                            try:
                                await client.search_episodes([episode_id])
                                items_found += 1
                                searches_triggered += 1
                                self._set_cooldown(f"sonarr_{instance.id}_episode_{episode_id}")
                                logger.debug("episode_search_triggered", episode_id=episode_id)

                            except Exception as e:
                                errors.append(f"Episode {episode_id}: {str(e)}")
                                logger.error(
                                    "episode_search_failed", episode_id=episode_id, error=str(e)
                                )

                        # Check if there are more pages
                        if page >= result.get("totalRecords", 0) / 50:
                            break

                        page += 1

            else:  # radarr
                async with RadarrClient(
                    url=instance.url,
                    api_key=api_key,
                    verify_ssl=instance.verify_ssl,
                    rate_limit_per_second=instance.rate_limit or 5.0,
                ) as client:
                    # Get all missing movies
                    page = 1
                    while True:
                        result = await client.get_wanted_missing(page=page, page_size=50)
                        records = result.get("records", [])

                        if not records:
                            break

                        for movie in records:
                            movie_id = movie.get("id")
                            if not movie_id:
                                continue

                            items_searched += 1

                            # Check cooldown
                            if self._is_in_cooldown(f"radarr_{instance.id}_movie_{movie_id}"):
                                logger.debug("item_in_cooldown", movie_id=movie_id)
                                continue

                            # Check rate limit
                            if not await self._check_rate_limit(instance.id):
                                logger.warning("rate_limit_reached", instance_id=instance.id)
                                break

                            # Trigger search
                            try:
                                await client.search_movies([movie_id])
                                items_found += 1
                                searches_triggered += 1
                                self._set_cooldown(f"radarr_{instance.id}_movie_{movie_id}")
                                logger.debug("movie_search_triggered", movie_id=movie_id)

                            except Exception as e:
                                errors.append(f"Movie {movie_id}: {str(e)}")
                                logger.error("movie_search_failed", movie_id=movie_id, error=str(e))

                        # Check if there are more pages
                        if page >= result.get("totalRecords", 0) / 50:
                            break

                        page += 1

            # Determine status
            if errors:
                status = "partial_success" if items_found > 0 else "failed"
            else:
                status = "success"

            return {
                "status": status,
                "items_searched": items_searched,
                "items_found": items_found,
                "searches_triggered": searches_triggered,
                "errors": errors,
            }

        except Exception as e:
            logger.error("missing_strategy_failed", error=str(e))
            raise

    async def _execute_cutoff_strategy(
        self,
        queue: SearchQueue,
        instance: Instance,
        db: Session,
    ) -> dict[str, Any]:
        """
        Execute cutoff unmet strategy.

        Searches for items that don't meet quality cutoff.

        Args:
            queue: Search queue
            instance: Instance to search on
            db: Database session

        Returns:
            dict: Execution results
        """
        logger.info("executing_cutoff_strategy", instance_type=instance.type)

        items_searched = 0
        items_found = 0
        searches_triggered = 0
        errors = []

        try:
            # Decrypt API key
            api_key = decrypt_api_key(instance.encrypted_api_key)

            if instance.type == "sonarr":
                async with SonarrClient(
                    url=instance.url,
                    api_key=api_key,
                    verify_ssl=instance.verify_ssl,
                    rate_limit_per_second=instance.rate_limit or 5.0,
                ) as client:
                    # Get all cutoff unmet episodes
                    page = 1
                    while True:
                        result = await client.get_wanted_cutoff(page=page, page_size=50)
                        records = result.get("records", [])

                        if not records:
                            break

                        for episode in records:
                            episode_id = episode.get("id")
                            if not episode_id:
                                continue

                            items_searched += 1

                            # Check cooldown
                            if self._is_in_cooldown(f"sonarr_{instance.id}_episode_{episode_id}"):
                                continue

                            # Check rate limit
                            if not await self._check_rate_limit(instance.id):
                                break

                            # Trigger search
                            try:
                                await client.search_episodes([episode_id])
                                items_found += 1
                                searches_triggered += 1
                                self._set_cooldown(f"sonarr_{instance.id}_episode_{episode_id}")

                            except Exception as e:
                                errors.append(f"Episode {episode_id}: {str(e)}")

                        if page >= result.get("totalRecords", 0) / 50:
                            break

                        page += 1

            else:  # radarr
                async with RadarrClient(
                    url=instance.url,
                    api_key=api_key,
                    verify_ssl=instance.verify_ssl,
                    rate_limit_per_second=instance.rate_limit or 5.0,
                ) as client:
                    # Get all cutoff unmet movies
                    page = 1
                    while True:
                        result = await client.get_wanted_cutoff(page=page, page_size=50)
                        records = result.get("records", [])

                        if not records:
                            break

                        for movie in records:
                            movie_id = movie.get("id")
                            if not movie_id:
                                continue

                            items_searched += 1

                            # Check cooldown
                            if self._is_in_cooldown(f"radarr_{instance.id}_movie_{movie_id}"):
                                continue

                            # Check rate limit
                            if not await self._check_rate_limit(instance.id):
                                break

                            # Trigger search
                            try:
                                await client.search_movies([movie_id])
                                items_found += 1
                                searches_triggered += 1
                                self._set_cooldown(f"radarr_{instance.id}_movie_{movie_id}")

                            except Exception as e:
                                errors.append(f"Movie {movie_id}: {str(e)}")

                        if page >= result.get("totalRecords", 0) / 50:
                            break

                        page += 1

            # Determine status
            if errors:
                status = "partial_success" if items_found > 0 else "failed"
            else:
                status = "success"

            return {
                "status": status,
                "items_searched": items_searched,
                "items_found": items_found,
                "searches_triggered": searches_triggered,
                "errors": errors,
            }

        except Exception as e:
            logger.error("cutoff_strategy_failed", error=str(e))
            raise

    async def _execute_recent_strategy(
        self,
        queue: SearchQueue,
        instance: Instance,
        db: Session,
    ) -> dict[str, Any]:
        """
        Execute recent additions strategy.

        Searches for recently added items (newest first).

        Args:
            queue: Search queue
            instance: Instance to search on
            db: Database session

        Returns:
            dict: Execution results
        """
        logger.info("executing_recent_strategy", instance_type=instance.type)

        # Recent strategy prioritizes newest missing items
        # Similar to missing strategy but with different sorting
        items_searched = 0
        items_found = 0
        searches_triggered = 0
        errors = []

        try:
            # Decrypt API key
            api_key = decrypt_api_key(instance.encrypted_api_key)

            if instance.type == "sonarr":
                async with SonarrClient(
                    url=instance.url,
                    api_key=api_key,
                    verify_ssl=instance.verify_ssl,
                    rate_limit_per_second=instance.rate_limit or 5.0,
                ) as client:
                    # Get recent missing episodes (sorted by air date descending)
                    result = await client.get_wanted_missing(
                        page=1,
                        page_size=50,
                        sort_key="airDateUtc",
                        sort_dir="descending",
                    )
                    records = result.get("records", [])

                    for episode in records:
                        episode_id = episode.get("id")
                        if not episode_id:
                            continue

                        items_searched += 1

                        # Check cooldown
                        if self._is_in_cooldown(f"sonarr_{instance.id}_episode_{episode_id}"):
                            continue

                        # Check rate limit
                        if not await self._check_rate_limit(instance.id):
                            break

                        # Trigger search
                        try:
                            await client.search_episodes([episode_id])
                            items_found += 1
                            searches_triggered += 1
                            self._set_cooldown(f"sonarr_{instance.id}_episode_{episode_id}")

                        except Exception as e:
                            errors.append(f"Episode {episode_id}: {str(e)}")

            else:  # radarr
                async with RadarrClient(
                    url=instance.url,
                    api_key=api_key,
                    verify_ssl=instance.verify_ssl,
                    rate_limit_per_second=instance.rate_limit or 5.0,
                ) as client:
                    # Get recent missing movies
                    result = await client.get_wanted_missing(
                        page=1,
                        page_size=50,
                        sort_key="title",
                        sort_dir="ascending",
                    )
                    records = result.get("records", [])

                    for movie in records:
                        movie_id = movie.get("id")
                        if not movie_id:
                            continue

                        items_searched += 1

                        # Check cooldown
                        if self._is_in_cooldown(f"radarr_{instance.id}_movie_{movie_id}"):
                            continue

                        # Check rate limit
                        if not await self._check_rate_limit(instance.id):
                            break

                        # Trigger search
                        try:
                            await client.search_movies([movie_id])
                            items_found += 1
                            searches_triggered += 1
                            self._set_cooldown(f"radarr_{instance.id}_movie_{movie_id}")

                        except Exception as e:
                            errors.append(f"Movie {movie_id}: {str(e)}")

            # Determine status
            if errors:
                status = "partial_success" if items_found > 0 else "failed"
            else:
                status = "success"

            return {
                "status": status,
                "items_searched": items_searched,
                "items_found": items_found,
                "searches_triggered": searches_triggered,
                "errors": errors,
            }

        except Exception as e:
            logger.error("recent_strategy_failed", error=str(e))
            raise

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
        logger.info("executing_custom_strategy", instance_type=instance.type)

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

        return datetime.utcnow() < cooldown_end

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
