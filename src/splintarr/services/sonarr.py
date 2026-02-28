"""
Sonarr API Client for Splintarr.

This module provides an async HTTP client for interacting with Sonarr v3 API:
- Connection testing and health monitoring
- Missing episodes retrieval
- Cutoff unmet episodes retrieval
- Search command triggering
- Quality profile management
- Series information retrieval

Features:
- Async httpx client with rate limiting
- Exponential backoff retry logic
- Comprehensive error handling
- Request/response logging
- Configurable timeouts and SSL verification
"""

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
# Sonarr-specific exception hierarchy
# ---------------------------------------------------------------------------


class SonarrError(ArrClientError):
    """Base exception for Sonarr API errors."""

    pass


class SonarrConnectionError(SonarrError, ArrConnectionError):
    """Exception raised when connection to Sonarr fails."""

    pass


class SonarrAuthenticationError(SonarrError, ArrAuthenticationError):
    """Exception raised when API authentication fails."""

    pass


class SonarrAPIError(SonarrError, ArrAPIError):
    """Exception raised when Sonarr API returns an error."""

    pass


class SonarrRateLimitError(SonarrError, ArrRateLimitError):
    """Exception raised when rate limit is exceeded."""

    pass


# ---------------------------------------------------------------------------
# Sonarr client
# ---------------------------------------------------------------------------


class SonarrClient(BaseArrClient):
    """
    Async HTTP client for Sonarr v3 API.

    Provides methods for:
    - Health monitoring and connection testing
    - Retrieving missing episodes
    - Retrieving cutoff unmet episodes
    - Triggering episode searches
    - Managing quality profiles
    - Accessing series information

    Rate limiting is enforced per instance to prevent overwhelming the Sonarr server.
    """

    service_name = "sonarr"
    _error_base = SonarrError
    _error_connection = SonarrConnectionError
    _error_auth = SonarrAuthenticationError
    _error_api = SonarrAPIError
    _error_rate = SonarrRateLimitError

    # Sonarr defaults for wanted endpoints
    _wanted_missing_sort_key = "airDateUtc"
    _wanted_missing_sort_dir = "descending"
    _wanted_cutoff_sort_key = "airDateUtc"
    _wanted_cutoff_sort_dir = "descending"

    async def search_episodes(self, episode_ids: list[int]) -> dict[str, Any]:
        """
        Trigger search for specific episodes.

        Args:
            episode_ids: List of episode IDs to search

        Returns:
            dict: Command response with status and ID

        Raises:
            SonarrError: If request fails
            ValueError: If episode_ids is empty
        """
        if not episode_ids:
            raise ValueError("episode_ids cannot be empty")

        command = {
            "name": "EpisodeSearch",
            "episodeIds": episode_ids,
        }

        result = await self._request("POST", "/api/v3/command", json=command)

        logger.info(
            "sonarr_episode_search_triggered",
            url=self.url,
            episode_ids=episode_ids,
            command_id=result.get("id"),
        )

        return result

    async def search_series(self, series_id: int) -> dict[str, Any]:
        """
        Trigger search for all missing episodes in a series.

        Args:
            series_id: Series ID to search

        Returns:
            dict: Command response with status and ID

        Raises:
            SonarrError: If request fails
        """
        command = {
            "name": "SeriesSearch",
            "seriesId": series_id,
        }

        result = await self._request("POST", "/api/v3/command", json=command)

        logger.info(
            "sonarr_series_search_triggered",
            url=self.url,
            series_id=series_id,
            command_id=result.get("id"),
        )

        return result

    async def get_series(
        self, series_id: int | None = None
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """
        Get series information.

        Args:
            series_id: Optional series ID. If None, returns all series.

        Returns:
            dict | list[dict]: Series information or list of all series

        Raises:
            SonarrError: If request fails
        """
        if series_id is not None:
            endpoint = f"/api/v3/series/{series_id}"
            result = await self._request("GET", endpoint)
            logger.debug("sonarr_series_retrieved", url=self.url, series_id=series_id)
        else:
            result = await self._request("GET", "/api/v3/series")
            logger.debug(
                "sonarr_all_series_retrieved",
                url=self.url,
                count=len(result) if isinstance(result, list) else 0,
            )

        return result

    async def get_episodes(self, series_id: int) -> list[dict[str, Any]]:
        """
        Get all episodes for a series.

        Args:
            series_id: Series ID to get episodes for

        Returns:
            list[dict]: List of episode records

        Raises:
            SonarrError: If request fails
        """
        result = await self._request(
            "GET", "/api/v3/episode", params={"seriesId": series_id}
        )
        episodes = result if isinstance(result, list) else []
        logger.debug(
            "sonarr_episodes_retrieved",
            url=self.url,
            series_id=series_id,
            count=len(episodes),
        )
        return episodes

    async def get_poster_bytes(self, series_id: int) -> bytes | None:
        """
        Download poster image for a series.

        Args:
            series_id: Series ID

        Returns:
            bytes | None: JPEG poster data, or None if unavailable
        """
        return await self._request_bytes(
            f"/api/v3/mediacover/{series_id}/poster.jpg"
        )
