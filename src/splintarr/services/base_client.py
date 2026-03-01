"""
Base *arr API client for Splintarr.

Provides the shared async HTTP client logic used by both SonarrClient and
RadarrClient, including:
- Lazy httpx client initialization with follow_redirects=False
- Per-instance rate limiting
- SSRF re-validation before every outbound request
- Retry with exponential backoff (tenacity)
- Comprehensive error handling for auth, rate-limit, redirect, 4xx, 5xx
- Connection testing, system status, wanted/missing, wanted/cutoff,
  quality profiles, and command status endpoints
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


# ---------------------------------------------------------------------------
# Base exception hierarchy
# ---------------------------------------------------------------------------


class ArrClientError(Exception):
    """Base exception for *arr API client errors."""

    pass


class ArrConnectionError(ArrClientError):
    """Exception raised when connection to an *arr instance fails."""

    pass


class ArrAuthenticationError(ArrClientError):
    """Exception raised when API authentication fails."""

    pass


class ArrAPIError(ArrClientError):
    """Exception raised when an *arr API returns an error."""

    pass


class ArrRateLimitError(ArrClientError):
    """Exception raised when rate limit is exceeded."""

    pass


# ---------------------------------------------------------------------------
# Base client
# ---------------------------------------------------------------------------


class BaseArrClient:
    """
    Async HTTP client base class for Sonarr/Radarr v3 APIs.

    Subclasses must set:
        service_name:  str — e.g. "sonarr" or "radarr"
        _error_base:   type[ArrClientError]
        _error_connection: type[ArrConnectionError]
        _error_auth:   type[ArrAuthenticationError]
        _error_api:    type[ArrAPIError]
        _error_rate:   type[ArrRateLimitError]

    Shared behaviour provided by this class:
        - Lazy httpx client (follow_redirects=False to prevent API key leakage)
        - Per-instance rate limiting
        - SSRF re-validation before every request (DNS-rebinding protection)
        - Exponential-backoff retries on transient connection/timeout errors
        - Structured logging with service-specific event names
    """

    # Subclasses must override these
    service_name: str = ""
    _error_base: type[ArrClientError] = ArrClientError
    _error_connection: type[ArrConnectionError] = ArrConnectionError
    _error_auth: type[ArrAuthenticationError] = ArrAuthenticationError
    _error_api: type[ArrAPIError] = ArrAPIError
    _error_rate: type[ArrRateLimitError] = ArrRateLimitError

    # Default sort parameters for wanted endpoints — subclasses can override
    _wanted_missing_sort_key: str = "airDateUtc"
    _wanted_missing_sort_dir: str = "descending"
    _wanted_cutoff_sort_key: str = "airDateUtc"
    _wanted_cutoff_sort_dir: str = "descending"

    def __init__(
        self,
        url: str,
        api_key: str,
        verify_ssl: bool = True,
        timeout: int = 30,
        rate_limit_per_second: float = 5.0,
    ):
        """
        Initialize *arr API client.

        Args:
            url: Base URL of the instance (e.g., https://sonarr.example.com)
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
            f"{self.service_name}_client_initialized",
            url=self.url,
            verify_ssl=verify_ssl,
            timeout=timeout,
            rate_limit_per_second=rate_limit_per_second,
        )

    # -- Async context manager --------------------------------------------------

    async def __aenter__(self):
        """Async context manager entry."""
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    # -- Client lifecycle -------------------------------------------------------

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
            logger.debug(f"{self.service_name}_http_client_created", url=self.url)

    async def close(self) -> None:
        """Close HTTP client and release resources."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.debug(f"{self.service_name}_http_client_closed", url=self.url)

    # -- Rate limiting ----------------------------------------------------------

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
                f"{self.service_name}_rate_limit_throttle",
                url=self.url,
                sleep_time=sleep_time,
            )
            await asyncio.sleep(sleep_time)

        self._last_request_time = time.time()

    # -- Core HTTP request with retries -----------------------------------------

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
        Make an HTTP request to the *arr API with retry logic.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (e.g., /api/v3/system/status)
            params: Optional query parameters
            json: Optional JSON body for POST/PUT requests

        Returns:
            dict | list: JSON response from API

        Raises:
            ArrConnectionError subclass: If connection fails after retries
            ArrAuthenticationError subclass: If API key is invalid
            ArrAPIError subclass: If API returns an error
            ArrRateLimitError subclass: If rate limit is exceeded
        """
        await self._ensure_client()
        await self._rate_limit()

        svc = self.service_name

        # Re-validate URL against SSRF immediately before each request to prevent
        # DNS rebinding attacks (TOCTOU: DNS may resolve differently than at config time)
        try:
            validate_instance_url(self.url, allow_local=settings.allow_local_instances)
        except SSRFError as e:
            logger.error(
                f"{svc}_ssrf_blocked",
                url=self.url,
                error=str(e),
            )
            raise self._error_connection(
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
                f"{svc}_api_request",
                method=method,
                endpoint=endpoint,
                status_code=response.status_code,
                duration_ms=int(request_duration * 1000),
            )

            # Handle authentication errors
            if response.status_code == 401:
                logger.error(f"{svc}_authentication_failed", url=self.url)
                raise self._error_auth("Invalid API key")

            # Handle rate limiting
            if response.status_code == 429:
                logger.warning(f"{svc}_rate_limit_exceeded", url=self.url)
                raise self._error_rate("Rate limit exceeded")

            # Handle redirects (don't follow -- prevents API key leaking to redirect target)
            if 300 <= response.status_code < 400:
                location = response.headers.get("Location", "unknown")
                logger.warning(
                    f"{svc}_redirect_not_followed",
                    url=self.url,
                    location=location,
                    status_code=response.status_code,
                )
                raise self._error_connection(
                    f"Instance returned redirect ({response.status_code}) to {location}. "
                    "Check the instance URL configuration."
                )

            # Handle client errors (4xx)
            if 400 <= response.status_code < 500:
                error_detail = response.text
                logger.error(
                    f"{svc}_client_error",
                    url=self.url,
                    status_code=response.status_code,
                    error=error_detail,
                )
                raise self._error_api(f"Client error ({response.status_code}): {error_detail}")

            # Handle server errors (5xx)
            if response.status_code >= 500:
                error_detail = response.text
                logger.error(
                    f"{svc}_server_error",
                    url=self.url,
                    status_code=response.status_code,
                    error=error_detail,
                )
                raise self._error_api(f"Server error ({response.status_code}): {error_detail}")

            # Raise for other non-success status codes
            response.raise_for_status()

            # Parse JSON response
            return response.json()

        except httpx.ConnectError as e:
            logger.error(f"{svc}_connection_failed", url=self.url, error=str(e))
            raise self._error_connection(f"Failed to connect to {svc.title()}: {e}") from e

        except httpx.TimeoutException as e:
            logger.error(f"{svc}_request_timeout", url=self.url, error=str(e))
            raise self._error_connection(f"Request timeout: {e}") from e

        except httpx.HTTPStatusError as e:
            logger.error(
                f"{svc}_http_error",
                url=self.url,
                status_code=e.response.status_code,
                error=str(e),
            )
            raise self._error_api(f"HTTP error: {e}") from e

        except ArrClientError:
            raise

        except Exception as e:
            logger.error(f"{svc}_unexpected_error", url=self.url, error=str(e))
            raise self._error_base(f"Unexpected error: {e}") from e

    async def _request_bytes(self, endpoint: str) -> bytes | None:
        """
        Download binary content (e.g., poster images) from the *arr API.

        Returns None on any error instead of raising, since missing
        posters are non-fatal.

        Args:
            endpoint: API endpoint path

        Returns:
            bytes | None: Raw response bytes, or None on failure
        """
        await self._ensure_client()
        assert self._client is not None  # guaranteed by _ensure_client()
        await self._rate_limit()

        # SSRF validation (same as _request)
        try:
            validate_instance_url(self.url, allow_local=settings.allow_local_instances)
        except SSRFError as e:
            logger.warning(
                f"{self.service_name}_binary_ssrf_blocked",
                url=self.url,
                endpoint=endpoint,
                error=str(e),
            )
            return None

        url = f"{self.url}{endpoint}"
        try:
            response = await self._client.request(method="GET", url=url)
            if response.status_code == 200:
                logger.debug(
                    f"{self.service_name}_binary_download_ok",
                    endpoint=endpoint,
                    size_bytes=len(response.content),
                )
                return response.content
            logger.debug(
                f"{self.service_name}_binary_request_non_200",
                endpoint=endpoint,
                status_code=response.status_code,
            )
            return None
        except Exception as e:
            logger.warning(
                f"{self.service_name}_binary_request_failed",
                endpoint=endpoint,
                error=str(e),
            )
            return None

    # -- Shared API endpoints ---------------------------------------------------

    async def test_connection(self) -> dict[str, Any]:
        """
        Test connection to the *arr instance.

        Returns:
            dict: Connection test result with keys:
                - success: bool
                - version: str | None
                - response_time_ms: int | None
                - error: str | None
        """
        try:
            start_time = time.time()
            result = await self._request("GET", "/api/v3/system/status")
            response_time_ms = int((time.time() - start_time) * 1000)

            version = result.get("version", "unknown")

            logger.info(
                f"{self.service_name}_connection_test_success",
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
                f"{self.service_name}_connection_test_failed",
                url=self.url,
                error=str(e),
            )
            return {
                "success": False,
                "version": None,
                "response_time_ms": None,
                "error": str(e),
            }

    async def get_system_status(self) -> dict[str, Any]:
        """
        Get system status.

        Returns:
            dict: System status information including version, startup path, etc.
        """
        return await self._request("GET", "/api/v3/system/status")

    async def get_wanted_missing(
        self,
        page: int = 1,
        page_size: int = 50,
        sort_key: str | None = None,
        sort_dir: str | None = None,
    ) -> dict[str, Any]:
        """
        Get missing items (not downloaded).

        Args:
            page: Page number (1-indexed, default: 1)
            page_size: Number of items per page (default: 50, max: 100)
            sort_key: Sort key (defaults to class-level _wanted_missing_sort_key)
            sort_dir: Sort direction (defaults to class-level _wanted_missing_sort_dir)

        Returns:
            dict: Paginated list of missing items
        """
        params = {
            "page": page,
            "pageSize": min(page_size, 100),
            "sortKey": sort_key or self._wanted_missing_sort_key,
            "sortDirection": sort_dir or self._wanted_missing_sort_dir,
        }

        result = await self._request("GET", "/api/v3/wanted/missing", params=params)

        logger.debug(
            f"{self.service_name}_missing_items_retrieved",
            url=self.url,
            total_records=result.get("totalRecords", 0),
            page=page,
        )

        return result

    async def get_wanted_cutoff(
        self,
        page: int = 1,
        page_size: int = 50,
        sort_key: str | None = None,
        sort_dir: str | None = None,
    ) -> dict[str, Any]:
        """
        Get items that don't meet quality cutoff.

        Args:
            page: Page number (1-indexed, default: 1)
            page_size: Number of items per page (default: 50, max: 100)
            sort_key: Sort key (defaults to class-level _wanted_cutoff_sort_key)
            sort_dir: Sort direction (defaults to class-level _wanted_cutoff_sort_dir)

        Returns:
            dict: Paginated list of cutoff unmet items
        """
        params = {
            "page": page,
            "pageSize": min(page_size, 100),
            "sortKey": sort_key or self._wanted_cutoff_sort_key,
            "sortDirection": sort_dir or self._wanted_cutoff_sort_dir,
        }

        result = await self._request("GET", "/api/v3/wanted/cutoff", params=params)

        logger.debug(
            f"{self.service_name}_cutoff_unmet_retrieved",
            url=self.url,
            total_records=result.get("totalRecords", 0),
            page=page,
        )

        return result

    async def get_quality_profiles(self) -> list[dict[str, Any]]:
        """
        Get all quality profiles.

        Returns:
            list[dict]: List of quality profiles with ID, name, and settings
        """
        result = await self._request("GET", "/api/v3/qualityprofile")

        logger.debug(
            f"{self.service_name}_quality_profiles_retrieved",
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
        """
        result = await self._request("GET", f"/api/v3/command/{command_id}")

        logger.debug(
            f"{self.service_name}_command_status_retrieved",
            url=self.url,
            command_id=command_id,
            state=result.get("status"),
        )

        return result
