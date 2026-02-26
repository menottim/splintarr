"""
Radarr API Client for Vibe-Quality-Searcharr.

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

import asyncio
import time
from typing import Any

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from vibe_quality_searcharr.config import settings

logger = structlog.get_logger()


class RadarrError(Exception):
    """Base exception for Radarr API errors."""

    pass


class RadarrConnectionError(RadarrError):
    """Exception raised when connection to Radarr fails."""

    pass


class RadarrAuthenticationError(RadarrError):
    """Exception raised when API authentication fails."""

    pass


class RadarrAPIError(RadarrError):
    """Exception raised when Radarr API returns an error."""

    pass


class RadarrRateLimitError(RadarrError):
    """Exception raised when rate limit is exceeded."""

    pass


class RadarrClient:
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

    def __init__(
        self,
        url: str,
        api_key: str,
        verify_ssl: bool = True,
        timeout: int = 30,
        rate_limit_per_second: float = 5.0,
    ):
        """
        Initialize Radarr API client.

        Args:
            url: Base URL of Radarr instance (e.g., https://radarr.example.com)
            api_key: API key for authentication (plaintext, not encrypted)
            verify_ssl: Whether to verify SSL certificates (default: True)
            timeout: Request timeout in seconds (default: 30)
            rate_limit_per_second: Maximum requests per second (default: 5.0)

        Raises:
            ValueError: If URL or API key is invalid
        """
        if not url or not url.startswith(("http://", "https://")):
            raise ValueError("Invalid URL: must start with http:// or https://")

        if not api_key or len(api_key) < 20:
            raise ValueError("Invalid API key: must be at least 20 characters")

        # Normalize URL (remove trailing slash)
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.verify_ssl = verify_ssl
        self.timeout = timeout

        # Rate limiting
        self.rate_limit_per_second = rate_limit_per_second
        self._min_interval = 1.0 / rate_limit_per_second
        self._last_request_time = 0.0

        # HTTP client (lazy initialization)
        self._client: httpx.AsyncClient | None = None

        logger.debug(
            "radarr_client_initialized",
            url=self.url,
            verify_ssl=verify_ssl,
            timeout=timeout,
            rate_limit_per_second=rate_limit_per_second,
        )

    async def __aenter__(self):
        """Async context manager entry."""
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def _ensure_client(self) -> None:
        """Ensure HTTP client is initialized."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                verify=self.verify_ssl,
                follow_redirects=True,  # httpx strips sensitive headers on cross-origin redirects
                headers={
                    "X-Api-Key": self.api_key,
                    "User-Agent": f"{settings.app_name}/0.1.0",
                },
            )
            logger.debug("radarr_http_client_created", url=self.url)

    async def close(self) -> None:
        """Close HTTP client and release resources."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.debug("radarr_http_client_closed", url=self.url)

    async def _rate_limit(self) -> None:
        """
        Enforce rate limiting.

        Ensures minimum time interval between requests based on configured rate limit.
        """
        current_time = time.time()
        time_since_last_request = current_time - self._last_request_time

        if time_since_last_request < self._min_interval:
            sleep_time = self._min_interval - time_since_last_request
            logger.debug(
                "radarr_rate_limit_throttle",
                url=self.url,
                sleep_time=sleep_time,
            )
            await asyncio.sleep(sleep_time)

        self._last_request_time = time.time()

    @retry(
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
        stop=stop_after_attempt(settings.api_max_retries),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """
        Make an HTTP request to Radarr API with retry logic.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (e.g., /api/v3/system/status)
            params: Optional query parameters
            json: Optional JSON body for POST/PUT requests

        Returns:
            dict | list: JSON response from API

        Raises:
            RadarrConnectionError: If connection fails after retries
            RadarrAuthenticationError: If API key is invalid
            RadarrAPIError: If API returns an error
            RadarrRateLimitError: If rate limit is exceeded
        """
        await self._ensure_client()
        await self._rate_limit()

        url = f"{self.url}{endpoint}"

        try:
            request_start = time.time()

            response = await self._client.request(
                method=method,
                url=url,
                params=params,
                json=json,
            )

            request_duration = time.time() - request_start

            logger.debug(
                "radarr_api_request",
                method=method,
                endpoint=endpoint,
                status_code=response.status_code,
                duration_ms=int(request_duration * 1000),
            )

            # Handle authentication errors
            if response.status_code == 401:
                logger.error("radarr_authentication_failed", url=self.url)
                raise RadarrAuthenticationError("Invalid API key")

            # Handle rate limiting
            if response.status_code == 429:
                logger.warning("radarr_rate_limit_exceeded", url=self.url)
                raise RadarrRateLimitError("Rate limit exceeded")

            # Handle client errors (4xx)
            if 400 <= response.status_code < 500:
                error_detail = response.text
                logger.error(
                    "radarr_client_error",
                    url=self.url,
                    status_code=response.status_code,
                    error=error_detail,
                )
                raise RadarrAPIError(f"Client error ({response.status_code}): {error_detail}")

            # Handle server errors (5xx)
            if response.status_code >= 500:
                error_detail = response.text
                logger.error(
                    "radarr_server_error",
                    url=self.url,
                    status_code=response.status_code,
                    error=error_detail,
                )
                raise RadarrAPIError(f"Server error ({response.status_code}): {error_detail}")

            # Raise for other non-success status codes
            response.raise_for_status()

            # Parse JSON response
            return response.json()

        except httpx.ConnectError as e:
            logger.error("radarr_connection_failed", url=self.url, error=str(e))
            raise RadarrConnectionError(f"Failed to connect to Radarr: {e}") from e

        except httpx.TimeoutException as e:
            logger.error("radarr_request_timeout", url=self.url, error=str(e))
            raise RadarrConnectionError(f"Request timeout: {e}") from e

        except httpx.HTTPStatusError as e:
            logger.error(
                "radarr_http_error",
                url=self.url,
                status_code=e.response.status_code,
                error=str(e),
            )
            raise RadarrAPIError(f"HTTP error: {e}") from e

        except Exception as e:
            logger.error("radarr_unexpected_error", url=self.url, error=str(e))
            raise RadarrError(f"Unexpected error: {e}") from e

    async def test_connection(self) -> dict[str, Any]:
        """
        Test connection to Radarr instance.

        Returns:
            dict: Connection test result with keys:
                - success: bool
                - version: str | None
                - response_time_ms: int | None
                - error: str | None

        Example:
            {
                "success": True,
                "version": "3.2.2.5080",
                "response_time_ms": 198,
                "error": None
            }
        """
        try:
            start_time = time.time()
            result = await self._request("GET", "/api/v3/system/status")
            response_time_ms = int((time.time() - start_time) * 1000)

            version = result.get("version", "unknown")

            logger.info(
                "radarr_connection_test_success",
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
            logger.error("radarr_connection_test_failed", url=self.url, error=str(e))
            return {
                "success": False,
                "version": None,
                "response_time_ms": None,
                "error": str(e),
            }

    async def get_system_status(self) -> dict[str, Any]:
        """
        Get Radarr system status.

        Returns:
            dict: System status information including version, startup path, etc.

        Raises:
            RadarrError: If request fails
        """
        return await self._request("GET", "/api/v3/system/status")

    async def get_wanted_missing(
        self,
        page: int = 1,
        page_size: int = 50,
        sort_key: str = "title",
        sort_dir: str = "ascending",
    ) -> dict[str, Any]:
        """
        Get missing movies (not downloaded).

        Args:
            page: Page number (1-indexed, default: 1)
            page_size: Number of items per page (default: 50, max: 100)
            sort_key: Sort key (default: title)
            sort_dir: Sort direction (ascending/descending, default: ascending)

        Returns:
            dict: Paginated list of missing movies with keys:
                - page: int
                - pageSize: int
                - totalRecords: int
                - records: list[dict]

        Raises:
            RadarrError: If request fails
        """
        params = {
            "page": page,
            "pageSize": min(page_size, 100),
            "sortKey": sort_key,
            "sortDirection": sort_dir,
        }

        result = await self._request("GET", "/api/v3/wanted/missing", params=params)

        logger.debug(
            "radarr_missing_movies_retrieved",
            url=self.url,
            total_records=result.get("totalRecords", 0),
            page=page,
        )

        return result

    async def get_wanted_cutoff(
        self,
        page: int = 1,
        page_size: int = 50,
        sort_key: str = "title",
        sort_dir: str = "ascending",
    ) -> dict[str, Any]:
        """
        Get movies that don't meet quality cutoff.

        Args:
            page: Page number (1-indexed, default: 1)
            page_size: Number of items per page (default: 50, max: 100)
            sort_key: Sort key (default: title)
            sort_dir: Sort direction (ascending/descending, default: ascending)

        Returns:
            dict: Paginated list of cutoff unmet movies

        Raises:
            RadarrError: If request fails
        """
        params = {
            "page": page,
            "pageSize": min(page_size, 100),
            "sortKey": sort_key,
            "sortDirection": sort_dir,
        }

        result = await self._request("GET", "/api/v3/wanted/cutoff", params=params)

        logger.debug(
            "radarr_cutoff_unmet_retrieved",
            url=self.url,
            total_records=result.get("totalRecords", 0),
            page=page,
        )

        return result

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

    async def get_quality_profiles(self) -> list[dict[str, Any]]:
        """
        Get all quality profiles.

        Returns:
            list[dict]: List of quality profiles with ID, name, and settings

        Raises:
            RadarrError: If request fails
        """
        result = await self._request("GET", "/api/v3/qualityprofile")

        logger.debug(
            "radarr_quality_profiles_retrieved",
            url=self.url,
            count=len(result) if isinstance(result, list) else 0,
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

    async def get_command_status(self, command_id: int) -> dict[str, Any]:
        """
        Get status of a command.

        Args:
            command_id: Command ID from previous command execution

        Returns:
            dict: Command status with state, progress, and result

        Raises:
            RadarrError: If request fails
        """
        result = await self._request("GET", f"/api/v3/command/{command_id}")

        logger.debug(
            "radarr_command_status_retrieved",
            url=self.url,
            command_id=command_id,
            state=result.get("status"),
        )

        return result
