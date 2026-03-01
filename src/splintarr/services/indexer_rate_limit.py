"""
Indexer rate limit service for Prowlarr-aware search throttling.

This module bridges the ProwlarrClient to the search execution pipeline.
It resolves the effective rate limit for a Sonarr/Radarr instance by reading
Prowlarr indexer data and computing the remaining query budget across all
connected indexers. Falls back to the instance's own rate_limit when Prowlarr
is unavailable, unconfigured, or has no applicable limits.

Key design decisions:
- Read-only: does NOT modify any data
- Fail-safe: any exception returns the instance fallback (Prowlarr is optional)
- Connected indexers are determined by tag intersection between the
  Prowlarr application and indexers (no tags on app = all indexers)
- Disabled indexers (circuit-breaker) are excluded from budget calculation
- Minimum remaining budget across all connected indexers is the effective cap
"""

from typing import Any
from urllib.parse import urlparse

import structlog
from sqlalchemy.orm import Session

from splintarr.core.security import decrypt_api_key
from splintarr.models.prowlarr import ProwlarrConfig
from splintarr.services.prowlarr import ProwlarrClient

logger = structlog.get_logger()


class IndexerRateLimitService:
    """
    Resolves effective rate limits by consulting Prowlarr indexer data.

    For each search run, this service checks whether the user has a Prowlarr
    connection configured. If so, it fetches indexer configurations, application
    mappings, and query statistics to compute the remaining query budget.

    The minimum remaining budget across all connected indexers is returned as
    ``max_items``, capping how many searches the queue can execute in one run.
    """

    def __init__(self, db: Session) -> None:
        """
        Initialize the service with a database session.

        Args:
            db: SQLAlchemy database session for querying ProwlarrConfig.
        """
        self.db = db

    async def get_effective_limit(
        self,
        instance_id: int,
        user_id: int,
        instance_rate: float,
        instance_url: str | None = None,
    ) -> dict[str, Any]:
        """
        Resolve the effective rate limit for a Sonarr/Radarr instance.

        Checks Prowlarr for indexer query budgets. If Prowlarr is configured
        and the instance can be matched to an application, returns the minimum
        remaining budget across connected indexers. Otherwise falls back to the
        instance's own rate limit.

        Args:
            instance_id: ID of the Sonarr/Radarr instance.
            user_id: ID of the user who owns the instance.
            instance_rate: Per-second rate limit from the instance config.
            instance_url: Base URL of the instance (for matching to Prowlarr app).

        Returns:
            dict with keys:
                - rate_per_second (float): The rate limit to use.
                - max_items (int | None): Maximum items to search, or None for unlimited.
                - source (str): "prowlarr" or "instance" indicating the limit source.
        """
        fallback = {
            "rate_per_second": instance_rate,
            "max_items": None,
            "source": "instance",
        }

        try:
            return await self._resolve_from_prowlarr(
                instance_id=instance_id,
                user_id=user_id,
                instance_rate=instance_rate,
                instance_url=instance_url,
                fallback=fallback,
            )
        except Exception as e:
            logger.warning(
                "indexer_rate_limit_prowlarr_failed",
                instance_id=instance_id,
                user_id=user_id,
                error=str(e),
            )
            return fallback

    async def _resolve_from_prowlarr(
        self,
        instance_id: int,
        user_id: int,
        instance_rate: float,
        instance_url: str | None,
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Internal: attempt to resolve rate limit from Prowlarr data.

        Args:
            instance_id: Instance ID for logging.
            user_id: User ID for querying ProwlarrConfig.
            instance_rate: Instance rate for the result dict.
            instance_url: Instance URL for application matching.
            fallback: Fallback dict to return if Prowlarr cannot provide a limit.

        Returns:
            Rate limit dict with prowlarr or instance source.
        """
        # Step 1: Look up ProwlarrConfig for user
        config = (
            self.db.query(ProwlarrConfig)
            .filter(
                ProwlarrConfig.user_id == user_id,
                ProwlarrConfig.is_active.is_(True),
            )
            .first()
        )

        if config is None:
            logger.debug(
                "indexer_rate_limit_no_prowlarr_config",
                instance_id=instance_id,
                user_id=user_id,
            )
            return fallback

        # Step 2: Decrypt API key and create client
        api_key = decrypt_api_key(config.encrypted_api_key)

        async with ProwlarrClient(
            url=config.url,
            api_key=api_key,
            verify_ssl=config.verify_ssl,
        ) as client:
            # Step 3: Fetch indexer data, applications, stats, and statuses
            indexers = await client.get_indexers()
            applications = await client.get_applications()
            daily_stats = await client.get_indexer_stats(hours=24)
            hourly_stats = await client.get_indexer_stats(hours=1)

            # BUG-3 fix: get_indexers() doesn't populate disabled_till;
            # fetch circuit-breaker status separately and build a lookup.
            indexer_statuses = await client.get_indexer_status()

        disabled_ids: set[int] = {
            s["indexer_id"] for s in indexer_statuses if s.get("disabled_till")
        }

        # Step 4: Match instance URL to a Prowlarr application
        if not instance_url:
            logger.debug(
                "indexer_rate_limit_no_instance_url",
                instance_id=instance_id,
                user_id=user_id,
            )
            return fallback

        matched_app = self._match_application(applications, instance_url)
        if matched_app is None:
            logger.debug(
                "indexer_rate_limit_no_matching_app",
                instance_id=instance_id,
                user_id=user_id,
                instance_url=instance_url,
            )
            return fallback

        # Step 5: Find connected indexers via tag intersection
        connected = self._get_connected_indexers(indexers, matched_app, disabled_ids)

        logger.debug(
            "indexer_rate_limit_connected_indexers",
            instance_id=instance_id,
            user_id=user_id,
            connected_count=len(connected),
            app_name=matched_app["name"],
        )

        # Step 7-8: Compute minimum remaining budget
        budgets: list[int] = []
        for indexer in connected:
            query_limit = indexer.get("query_limit")
            if query_limit is None:
                continue

            indexer_id = indexer["id"]
            # BUG-2 fix: use hourly stats for hour-limited indexers,
            # daily stats for day-limited (or unspecified) indexers.
            limits_unit = indexer.get("limits_unit")
            if limits_unit == "hour":
                indexer_stats = hourly_stats.get(indexer_id, {})
            else:
                indexer_stats = daily_stats.get(indexer_id, {})
            queries_used = indexer_stats.get("queries", 0)
            remaining = max(0, query_limit - queries_used)

            logger.debug(
                "indexer_rate_limit_budget_calculated",
                instance_id=instance_id,
                indexer_id=indexer_id,
                indexer_name=indexer["name"],
                query_limit=query_limit,
                queries_used=queries_used,
                remaining=remaining,
            )

            budgets.append(remaining)

        # Step 9: No indexers with limits -> fallback
        if not budgets:
            logger.debug(
                "indexer_rate_limit_no_indexer_limits",
                instance_id=instance_id,
                user_id=user_id,
            )
            return fallback

        effective_max = min(budgets)

        logger.info(
            "indexer_rate_limit_resolved",
            instance_id=instance_id,
            user_id=user_id,
            max_items=effective_max,
            source="prowlarr",
            indexer_count=len(connected),
            budgets=budgets,
        )

        return {
            "rate_per_second": instance_rate,
            "max_items": effective_max,
            "source": "prowlarr",
        }

    @staticmethod
    def _match_application(
        applications: list[dict[str, Any]],
        instance_url: str,
    ) -> dict[str, Any] | None:
        """
        Match an instance URL to a Prowlarr application by hostname comparison.

        Compares the netloc (hostname:port) from the instance URL against each
        application's base_url. This handles differences in protocol (http vs
        https) and trailing paths.

        Args:
            applications: List of application dicts from ProwlarrClient.get_applications().
            instance_url: Base URL of the Sonarr/Radarr instance.

        Returns:
            The matching application dict, or None if no match found.
        """
        instance_netloc = urlparse(instance_url).netloc.lower()
        if not instance_netloc:
            return None

        for app in applications:
            app_url = app.get("base_url")
            if not app_url:
                continue

            app_netloc = urlparse(app_url).netloc.lower()
            if app_netloc == instance_netloc:
                return app

        return None

    @staticmethod
    def _get_connected_indexers(
        indexers: list[dict[str, Any]],
        app: dict[str, Any],
        disabled_ids: set[int] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Filter indexers connected to a Prowlarr application via tag intersection.

        If the application has no tags, all indexers are considered connected
        (Prowlarr default behaviour). If the application has tags, only indexers
        sharing at least one tag are included.

        Disabled indexers (identified via ``disabled_ids`` from the indexer
        status endpoint) are always excluded.

        Args:
            indexers: List of indexer dicts from ProwlarrClient.get_indexers().
            app: Application dict from ProwlarrClient.get_applications().
            disabled_ids: Set of indexer IDs that are currently disabled
                (from ``get_indexer_status()``).

        Returns:
            Filtered list of connected, non-disabled indexers.
        """
        app_tags = set(app.get("tags", []))
        _disabled_ids = disabled_ids or set()
        connected: list[dict[str, Any]] = []

        for indexer in indexers:
            # Step 6: Skip disabled indexers (from indexer status endpoint)
            if indexer["id"] in _disabled_ids:
                continue

            # No tags on app means all indexers are connected
            if not app_tags:
                connected.append(indexer)
                continue

            # Tag intersection: at least one shared tag
            indexer_tags = set(indexer.get("tags", []))
            if app_tags & indexer_tags:
                connected.append(indexer)

        return connected
