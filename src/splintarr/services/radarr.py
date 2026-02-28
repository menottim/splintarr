"""
Radarr API Client for Splintarr.

This module provides an async HTTP client for interacting with Radarr v3 API:
- Connection testing and health monitoring
- Missing movies retrieval
- Cutoff unmet movies retrieval
- Search command triggering
- Quality profile management
- Movie information retrieval

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
# Radarr-specific exception hierarchy
# ---------------------------------------------------------------------------


class RadarrError(ArrClientError):
    """Base exception for Radarr API errors."""

    pass


class RadarrConnectionError(RadarrError, ArrConnectionError):
    """Exception raised when connection to Radarr fails."""

    pass


class RadarrAuthenticationError(RadarrError, ArrAuthenticationError):
    """Exception raised when API authentication fails."""

    pass


class RadarrAPIError(RadarrError, ArrAPIError):
    """Exception raised when Radarr API returns an error."""

    pass


class RadarrRateLimitError(RadarrError, ArrRateLimitError):
    """Exception raised when rate limit is exceeded."""

    pass


# ---------------------------------------------------------------------------
# Radarr client
# ---------------------------------------------------------------------------


class RadarrClient(BaseArrClient):
    """
    Async HTTP client for Radarr v3 API.

    Provides methods for:
    - Health monitoring and connection testing
    - Retrieving missing movies
    - Retrieving cutoff unmet movies
    - Triggering movie searches
    - Managing quality profiles
    - Accessing movie information

    Rate limiting is enforced per instance to prevent overwhelming the Radarr server.
    """

    service_name = "radarr"
    _error_base = RadarrError
    _error_connection = RadarrConnectionError
    _error_auth = RadarrAuthenticationError
    _error_api = RadarrAPIError
    _error_rate = RadarrRateLimitError

    # Radarr defaults for wanted endpoints
    _wanted_missing_sort_key = "title"
    _wanted_missing_sort_dir = "ascending"
    _wanted_cutoff_sort_key = "title"
    _wanted_cutoff_sort_dir = "ascending"

    async def search_movies(self, movie_ids: list[int]) -> dict[str, Any]:
        """
        Trigger search for specific movies.

        Args:
            movie_ids: List of movie IDs to search

        Returns:
            dict: Command response with status and ID

        Raises:
            RadarrError: If request fails
            ValueError: If movie_ids is empty
        """
        if not movie_ids:
            raise ValueError("movie_ids cannot be empty")

        command = {
            "name": "MoviesSearch",
            "movieIds": movie_ids,
        }

        result = await self._request("POST", "/api/v3/command", json=command)

        logger.info(
            "radarr_movie_search_triggered",
            url=self.url,
            movie_ids=movie_ids,
            command_id=result.get("id"),
        )

        return result

    async def get_movies(
        self, movie_id: int | None = None
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """
        Get movie information.

        Args:
            movie_id: Optional movie ID. If None, returns all movies.

        Returns:
            dict | list[dict]: Movie information or list of all movies

        Raises:
            RadarrError: If request fails
        """
        if movie_id is not None:
            endpoint = f"/api/v3/movie/{movie_id}"
            result = await self._request("GET", endpoint)
            logger.debug("radarr_movie_retrieved", url=self.url, movie_id=movie_id)
        else:
            result = await self._request("GET", "/api/v3/movie")
            logger.debug(
                "radarr_all_movies_retrieved",
                url=self.url,
                count=len(result) if isinstance(result, list) else 0,
            )

        return result

    async def get_poster_bytes(self, movie_id: int) -> bytes | None:
        """
        Download poster image for a movie.

        Args:
            movie_id: Movie ID

        Returns:
            bytes | None: JPEG poster data, or None if unavailable
        """
        return await self._request_bytes(
            f"/api/v3/mediacover/{movie_id}/poster.jpg"
        )
