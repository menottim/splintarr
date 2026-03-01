"""
Prowlarr API Client for Splintarr.

This module provides an async HTTP client for interacting with Prowlarr v1 API:
- Indexer retrieval with rate limit field parsing
- Application (Sonarr/Radarr) discovery
- Indexer statistics retrieval
- Indexer status (circuit-breaker) monitoring

Features:
- Async httpx client with rate limiting
- Exponential backoff retry logic
- Comprehensive error handling
- Request/response logging
- Configurable timeouts and SSL verification

Prowlarr uses API v1 (not v3 like Sonarr/Radarr). Rate limit fields
(QueryLimit, GrabLimit, LimitsUnit) are nested inside each indexer's
``fields`` array rather than being top-level properties.
"""

import time
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from splintarr.services.base_client import (
    ArrAPIError,
    ArrAuthenticationError,
    ArrClientError,
    ArrConnectionError,
    ArrRateLimitError,
    BaseArrClient,
)

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Prowlarr-specific exception hierarchy
# ---------------------------------------------------------------------------


class ProwlarrError(ArrClientError):
    """Base exception for Prowlarr API errors."""

    pass


class ProwlarrConnectionError(ProwlarrError, ArrConnectionError):
    """Exception raised when connection to Prowlarr fails."""

    pass


class ProwlarrAuthenticationError(ProwlarrError, ArrAuthenticationError):
    """Exception raised when API authentication fails."""

    pass


class ProwlarrAPIError(ProwlarrError, ArrAPIError):
    """Exception raised when Prowlarr API returns an error."""

    pass


class ProwlarrRateLimitError(ProwlarrError, ArrRateLimitError):
    """Exception raised when rate limit is exceeded."""

    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Prowlarr LimitsUnit enum values
_LIMITS_UNIT_MAP: dict[int, str] = {
    0: "day",
    1: "hour",
}


def _extract_field(fields: list[dict[str, Any]], name: str) -> Any:
    """
    Extract a value from a Prowlarr nested ``fields`` array by field name.

    Args:
        fields: List of ``{"name": ..., "value": ...}`` dicts.
        name: The field name to search for (e.g. ``"QueryLimit"``).

    Returns:
        The field's ``value``, or ``None`` if not found.
    """
    for field in fields:
        if field.get("name") == name:
            return field.get("value")
    return None


# ---------------------------------------------------------------------------
# Prowlarr client
# ---------------------------------------------------------------------------


class ProwlarrClient(BaseArrClient):
    """
    Async HTTP client for Prowlarr v1 API.

    Provides methods for:
    - Retrieving indexer configurations with parsed rate limits
    - Discovering connected applications (Sonarr/Radarr instances)
    - Fetching indexer query/grab statistics
    - Monitoring indexer circuit-breaker status

    Rate limiting is enforced per instance to prevent overwhelming the
    Prowlarr server.
    """

    service_name = "prowlarr"
    _error_base = ProwlarrError
    _error_connection = ProwlarrConnectionError
    _error_auth = ProwlarrAuthenticationError
    _error_api = ProwlarrAPIError
    _error_rate = ProwlarrRateLimitError

    async def test_connection(self) -> dict[str, Any]:
        """
        Test connection to Prowlarr.

        Overrides BaseArrClient.test_connection() because Prowlarr uses
        ``/api/v1`` instead of ``/api/v3``.

        Returns:
            dict: Connection test result with keys:
                - success: bool
                - version: str | None
                - response_time_ms: int | None
                - error: str | None
        """
        try:
            start_time = time.time()
            result = await self._request("GET", "/api/v1/system/status")
            response_time_ms = int((time.time() - start_time) * 1000)

            version = result.get("version", "unknown")

            logger.info(
                "prowlarr_connection_test_success",
                url=self.url,
                version=version,
                response_time_ms=response_time_ms,
            )

            return {
                "success": True,
                "version": version,
                "response_time_ms": response_time_ms,
                "error": None,
            }

        except Exception as e:
            logger.error(
                "prowlarr_connection_test_failed",
                url=self.url,
                error=str(e),
            )
            return {
                "success": False,
                "version": None,
                "response_time_ms": None,
                "error": str(e),
            }

    async def get_indexers(self) -> list[dict[str, Any]]:
        """
        Get all configured indexers with parsed rate limit information.

        Prowlarr stores rate limit fields (QueryLimit, GrabLimit, LimitsUnit)
        inside each indexer's nested ``fields`` array. This method extracts
        them into flat, snake_case keys for downstream consumption.

        LimitsUnit values: ``0`` = Day, ``1`` = Hour.

        Returns:
            list[dict]: List of indexer dicts with keys:
                - id (int)
                - name (str)
                - enable (bool)
                - protocol (str)
                - query_limit (int | None)
                - grab_limit (int | None)
                - limits_unit (str | None) — ``"hour"`` or ``"day"``
                - tags (list[int])
                - disabled_till (str | None)

        Raises:
            ProwlarrError: If request fails
        """
        logger.info("prowlarr_get_indexers_started", url=self.url)

        raw = await self._request("GET", "/api/v1/indexer")
        indexers: list[dict[str, Any]] = []

        for item in raw:
            fields: list[dict[str, Any]] = item.get("fields") or []

            query_limit = _extract_field(fields, "QueryLimit")
            grab_limit = _extract_field(fields, "GrabLimit")
            limits_unit_raw = _extract_field(fields, "LimitsUnit")
            limits_unit = (
                _LIMITS_UNIT_MAP.get(limits_unit_raw) if limits_unit_raw is not None else None
            )

            indexers.append(
                {
                    "id": item["id"],
                    "name": item["name"],
                    "enable": item.get("enable", False),
                    "protocol": item.get("protocol", ""),
                    "query_limit": query_limit,
                    "grab_limit": grab_limit,
                    "limits_unit": limits_unit,
                    "tags": item.get("tags", []),
                    "disabled_till": item.get("disabledTill"),
                }
            )

        logger.info(
            "prowlarr_get_indexers_completed",
            url=self.url,
            count=len(indexers),
        )

        return indexers

    async def get_applications(self) -> list[dict[str, Any]]:
        """
        Get all configured applications (Sonarr, Radarr, etc.).

        The BaseUrl field is extracted from each application's nested
        ``fields`` array.

        Returns:
            list[dict]: List of application dicts with keys:
                - id (int)
                - name (str)
                - implementation (str)
                - base_url (str | None)
                - tags (list[int])

        Raises:
            ProwlarrError: If request fails
        """
        logger.info("prowlarr_get_applications_started", url=self.url)

        raw = await self._request("GET", "/api/v1/applications")
        applications: list[dict[str, Any]] = []

        for item in raw:
            fields: list[dict[str, Any]] = item.get("fields") or []
            base_url = _extract_field(fields, "BaseUrl")

            applications.append(
                {
                    "id": item["id"],
                    "name": item["name"],
                    "implementation": item.get("implementation", ""),
                    "base_url": base_url,
                    "tags": item.get("tags", []),
                }
            )

        logger.info(
            "prowlarr_get_applications_completed",
            url=self.url,
            count=len(applications),
        )

        return applications

    async def get_indexer_stats(self, hours: int = 24) -> dict[int, dict[str, Any]]:
        """
        Get indexer query/grab statistics for the given time window.

        Args:
            hours: Number of hours to look back (default: 24).

        Returns:
            dict: Keyed by indexer_id, each value is a dict with:
                - name (str)
                - queries (int)
                - grabs (int)
                - failed_queries (int)

        Raises:
            ProwlarrError: If request fails
        """
        logger.info(
            "prowlarr_get_indexer_stats_started",
            url=self.url,
            hours=hours,
        )

        now = datetime.now(UTC)
        start = now - timedelta(hours=hours)

        params = {
            "startDate": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endDate": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        raw = await self._request("GET", "/api/v1/indexerstats", params=params)
        stats: dict[int, dict[str, Any]] = {}

        for item in raw.get("indexers", []):
            indexer_id = item["indexerId"]
            stats[indexer_id] = {
                "name": item.get("indexerName", ""),
                "queries": item.get("numberOfQueries", 0),
                "grabs": item.get("numberOfGrabs", 0),
                "failed_queries": item.get("numberOfFailedQueries", 0),
            }

        logger.info(
            "prowlarr_get_indexer_stats_completed",
            url=self.url,
            indexer_count=len(stats),
            hours=hours,
        )

        return stats

    async def get_indexer_status(self) -> list[dict[str, Any]]:
        """
        Get indexer circuit-breaker status (disabled indexers).

        Returns:
            list[dict]: List of status entries with keys:
                - indexer_id (int)
                - disabled_till (str | None) — ISO datetime or None

        Raises:
            ProwlarrError: If request fails
        """
        logger.info("prowlarr_get_indexer_status_started", url=self.url)

        raw = await self._request("GET", "/api/v1/indexerstatus")
        statuses: list[dict[str, Any]] = []

        for item in raw:
            statuses.append(
                {
                    "indexer_id": item["indexerId"],
                    "disabled_till": item.get("disabledTill"),
                }
            )

        logger.info(
            "prowlarr_get_indexer_status_completed",
            url=self.url,
            disabled_count=len(statuses),
        )

        return statuses
