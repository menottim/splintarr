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

from splintarr.config import settings
from splintarr.core.ssrf_protection import SSRFError, validate_instance_url

logger = structlog.get_logger()


class SonarrError(Exception):
    """Base exception for Sonarr API errors."""

    pass


class SonarrConnectionError(SonarrError):
    """Exception raised when connection to Sonarr fails."""

    pass


class SonarrAuthenticationError(SonarrError):
    """Exception raised when API authentication fails."""

    pass


class SonarrAPIError(SonarrError):
    """Exception raised when Sonarr API returns an error."""

    pass


class SonarrRateLimitError(SonarrError):
    """Exception raised when rate limit is exceeded."""

    pass


class SonarrClient:
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

    def __init__(
        self,
        url: str,
        api_key: str,
        verify_ssl: bool = True,
        timeout: int = 30,
        rate_limit_per_second: float = 5.0,
    ):
        """
        Initialize Sonarr API client.

        Args:
            url: Base URL of Sonarr instance (e.g., https://sonarr.example.com)
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
            "sonarr_client_initialized",
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
                follow_redirects=False,  # Disabled: prevents X-Api-Key leaking to redirect targets
                headers={
                    "X-Api-Key": self.api_key,
                    "User-Agent": f"{settings.app_name}/0.1.0",
                },
            )
            logger.debug("sonarr_http_client_created", url=self.url)

    async def close(self) -> None:
        """Close HTTP client and release resources."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.debug("sonarr_http_client_closed", url=self.url)

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
                "sonarr_rate_limit_throttle",
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
        Make an HTTP request to Sonarr API with retry logic.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (e.g., /api/v3/system/status)
            params: Optional query parameters
            json: Optional JSON body for POST/PUT requests

        Returns:
            dict | list: JSON response from API

        Raises:
            SonarrConnectionError: If connection fails after retries
            SonarrAuthenticationError: If API key is invalid
            SonarrAPIError: If API returns an error
            SonarrRateLimitError: If rate limit is exceeded
        """
        await self._ensure_client()
        await self._rate_limit()

        # Re-validate URL against SSRF immediately before each request to prevent
        # DNS rebinding attacks (TOCTOU: DNS may resolve differently than at config time)
        try:
            validate_instance_url(
                self.url, allow_local=settings.allow_local_instances
            )
        except SSRFError as e:
            logger.error(
                "sonarr_ssrf_blocked",
                url=self.url,
                error=str(e),
            )
            raise SonarrConnectionError(
                f"SSRF protection blocked request to {self.url}: {e}"
            ) from e

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
                "sonarr_api_request",
                method=method,
                endpoint=endpoint,
                status_code=response.status_code,
                duration_ms=int(request_duration * 1000),
            )

            # Handle authentication errors
            if response.status_code == 401:
                logger.error("sonarr_authentication_failed", url=self.url)
                raise SonarrAuthenticationError("Invalid API key")

            # Handle rate limiting
            if response.status_code == 429:
                logger.warning("sonarr_rate_limit_exceeded", url=self.url)
                raise SonarrRateLimitError("Rate limit exceeded")

            # Handle redirects (don't follow — prevents API key leaking to redirect target)
            if 300 <= response.status_code < 400:
                location = response.headers.get("Location", "unknown")
                logger.warning(
                    "sonarr_redirect_not_followed",
                    url=self.url,
                    location=location,
                    status_code=response.status_code,
                )
                raise SonarrConnectionError(
                    f"Instance returned redirect ({response.status_code}) to {location}. "
                    "Check the instance URL configuration."
                )

            # Handle client errors (4xx)
            if 400 <= response.status_code < 500:
                error_detail = response.text
                logger.error(
                    "sonarr_client_error",
                    url=self.url,
                    status_code=response.status_code,
                    error=error_detail,
                )
                raise SonarrAPIError(f"Client error ({response.status_code}): {error_detail}")

            # Handle server errors (5xx)
            if response.status_code >= 500:
                error_detail = response.text
                logger.error(
                    "sonarr_server_error",
                    url=self.url,
                    status_code=response.status_code,
                    error=error_detail,
                )
                raise SonarrAPIError(f"Server error ({response.status_code}): {error_detail}")

            # Raise for other non-success status codes
            response.raise_for_status()

            # Parse JSON response
            return response.json()

        except httpx.ConnectError as e:
            logger.error("sonarr_connection_failed", url=self.url, error=str(e))
            raise SonarrConnectionError(f"Failed to connect to Sonarr: {e}") from e

        except httpx.TimeoutException as e:
            logger.error("sonarr_request_timeout", url=self.url, error=str(e))
            raise SonarrConnectionError(f"Request timeout: {e}") from e

        except httpx.HTTPStatusError as e:
            logger.error(
                "sonarr_http_error",
                url=self.url,
                status_code=e.response.status_code,
                error=str(e),
            )
            raise SonarrAPIError(f"HTTP error: {e}") from e

        except SonarrError:
            raise

        except Exception as e:
            logger.error("sonarr_unexpected_error", url=self.url, error=str(e))
            raise SonarrError(f"Unexpected error: {e}") from e

    async def test_connection(self) -> dict[str, Any]:
        """
        Test connection to Sonarr instance.

        Returns:
            dict: Connection test result with keys:
                - success: bool
                - version: str | None
                - response_time_ms: int | None
                - error: str | None

        Example:
            {
                "success": True,
                "version": "3.0.10.1567",
                "response_time_ms": 245,
                "error": None
            }
        """
        try:
            start_time = time.time()
            result = await self._request("GET", "/api/v3/system/status")
            response_time_ms = int((time.time() - start_time) * 1000)

            version = result.get("version", "unknown")

            logger.info(
                "sonarr_connection_test_success",
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
            logger.error("sonarr_connection_test_failed", url=self.url, error=str(e))
            return {
                "success": False,
                "version": None,
                "response_time_ms": None,
                "error": str(e),
            }

    async def get_system_status(self) -> dict[str, Any]:
        """
        Get Sonarr system status.

        Returns:
            dict: System status information including version, startup path, etc.

        Raises:
            SonarrError: If request fails
        """
        return await self._request("GET", "/api/v3/system/status")

    async def get_wanted_missing(
        self,
        page: int = 1,
        page_size: int = 50,
        sort_key: str = "airDateUtc",
        sort_dir: str = "descending",
    ) -> dict[str, Any]:
        """
        Get missing episodes (not downloaded).

        Args:
            page: Page number (1-indexed, default: 1)
            page_size: Number of items per page (default: 50, max: 100)
            sort_key: Sort key (default: airDateUtc)
            sort_dir: Sort direction (ascending/descending, default: descending)

        Returns:
            dict: Paginated list of missing episodes with keys:
                - page: int
                - pageSize: int
                - totalRecords: int
                - records: list[dict]

        Raises:
            SonarrError: If request fails
        """
        params = {
            "page": page,
            "pageSize": min(page_size, 100),
            "sortKey": sort_key,
            "sortDirection": sort_dir,
        }

        result = await self._request("GET", "/api/v3/wanted/missing", params=params)

        logger.debug(
            "sonarr_missing_episodes_retrieved",
            url=self.url,
            total_records=result.get("totalRecords", 0),
            page=page,
        )

        return result

    async def get_wanted_cutoff(
        self,
        page: int = 1,
        page_size: int = 50,
        sort_key: str = "airDateUtc",
        sort_dir: str = "descending",
    ) -> dict[str, Any]:
        """
        Get episodes that don't meet quality cutoff.

        Args:
            page: Page number (1-indexed, default: 1)
            page_size: Number of items per page (default: 50, max: 100)
            sort_key: Sort key (default: airDateUtc)
            sort_dir: Sort direction (ascending/descending, default: descending)

        Returns:
            dict: Paginated list of cutoff unmet episodes

        Raises:
            SonarrError: If request fails
        """
        params = {
            "page": page,
            "pageSize": min(page_size, 100),
            "sortKey": sort_key,
            "sortDirection": sort_dir,
        }

        result = await self._request("GET", "/api/v3/wanted/cutoff", params=params)

        logger.debug(
            "sonarr_cutoff_unmet_retrieved",
            url=self.url,
            total_records=result.get("totalRecords", 0),
            page=page,
        )

        return result

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

    async def get_quality_profiles(self) -> list[dict[str, Any]]:
        """
        Get all quality profiles.

        Returns:
            list[dict]: List of quality profiles with ID, name, and settings

        Raises:
            SonarrError: If request fails
        """
        result = await self._request("GET", "/api/v3/qualityprofile")

        logger.debug(
            "sonarr_quality_profiles_retrieved",
            url=self.url,
            count=len(result) if isinstance(result, list) else 0,
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

    async def get_command_status(self, command_id: int) -> dict[str, Any]:
        """
        Get status of a command.

        Args:
            command_id: Command ID from previous command execution

        Returns:
            dict: Command status with state, progress, and result

        Raises:
            SonarrError: If request fails
        """
        result = await self._request("GET", f"/api/v3/command/{command_id}")

        logger.debug(
            "sonarr_command_status_retrieved",
            url=self.url,
            command_id=command_id,
            state=result.get("status"),
        )

        return result
