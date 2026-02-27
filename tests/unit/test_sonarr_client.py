"""
Unit tests for Sonarr API client.

Tests cover:
- Client initialization and validation
- Connection testing
- API endpoint calls
- Rate limiting behavior
- Error handling and retry logic
- Connection failures
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from splintarr.services.sonarr import (
    SonarrAPIError,
    SonarrAuthenticationError,
    SonarrClient,
    SonarrConnectionError,
    SonarrRateLimitError,
)


class TestSonarrClientInitialization:
    """Test Sonarr client initialization and validation."""

    def test_valid_initialization(self):
        """Test successful client initialization."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
            verify_ssl=True,
            timeout=30,
            rate_limit_per_second=5.0,
        )

        assert client.url == "https://sonarr.example.com"
        assert client.api_key == "a" * 32
        assert client.verify_ssl is True
        assert client.timeout == 30
        assert client.rate_limit_per_second == 5.0

    def test_url_normalization(self):
        """Test URL trailing slash removal."""
        client = SonarrClient(
            url="https://sonarr.example.com/",
            api_key="a" * 32,
        )

        assert client.url == "https://sonarr.example.com"

    def test_invalid_url(self):
        """Test initialization with invalid URL."""
        with pytest.raises(ValueError, match="Invalid URL"):
            SonarrClient(
                url="not-a-url",
                api_key="a" * 32,
            )

    def test_empty_url(self):
        """Test initialization with empty URL."""
        with pytest.raises(ValueError, match="Invalid URL"):
            SonarrClient(
                url="",
                api_key="a" * 32,
            )

    def test_invalid_api_key_too_short(self):
        """Test initialization with too short API key."""
        with pytest.raises(ValueError, match="Invalid API key"):
            SonarrClient(
                url="https://sonarr.example.com",
                api_key="short",
            )

    def test_empty_api_key(self):
        """Test initialization with empty API key."""
        with pytest.raises(ValueError, match="Invalid API key"):
            SonarrClient(
                url="https://sonarr.example.com",
                api_key="",
            )


class TestSonarrClientContextManager:
    """Test async context manager functionality."""

    @pytest.mark.asyncio
    async def test_context_manager_creates_client(self):
        """Test that context manager initializes HTTP client."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        assert client._client is None

        async with client:
            assert client._client is not None
            assert isinstance(client._client, httpx.AsyncClient)

        # Client should be closed after exiting context
        assert client._client is None

    @pytest.mark.asyncio
    async def test_context_manager_closes_client(self):
        """Test that context manager closes HTTP client."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        async with client:
            http_client = client._client

        # Verify client was closed
        assert client._client is None
        # HTTP client should be closed
        assert http_client.is_closed


class TestSonarrRateLimiting:
    """Test rate limiting functionality."""

    @pytest.mark.asyncio
    async def test_rate_limiting_enforced(self):
        """Test that rate limiting delays requests."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
            rate_limit_per_second=10.0,  # 10 requests per second = 0.1s interval
        )

        # Mock the HTTP client to avoid actual requests
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"version": "3.0.0"}

        with patch.object(client, "_ensure_client", new_callable=AsyncMock):
            client._client = AsyncMock()
            client._client.request = AsyncMock(return_value=mock_response)

            # Make multiple requests and measure time
            start_time = time.time()
            await client._request("GET", "/api/v3/system/status")
            await client._request("GET", "/api/v3/system/status")
            elapsed = time.time() - start_time

            # Should take at least 0.1 seconds due to rate limiting
            assert elapsed >= 0.09  # Allow small margin for timing

    @pytest.mark.asyncio
    async def test_rate_limit_calculation(self):
        """Test rate limit interval calculation."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
            rate_limit_per_second=5.0,
        )

        assert client._min_interval == 0.2  # 1 / 5 = 0.2 seconds


class TestSonarrConnectionTesting:
    """Test connection testing functionality."""

    @pytest.mark.asyncio
    async def test_successful_connection_test(self):
        """Test successful connection test."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "version": "3.0.10.1567",
            "instanceName": "Test Sonarr",
        }

        with patch.object(client, "_request") as mock_request:
            mock_request.return_value = mock_response.json.return_value

            result = await client.test_connection()

            assert result["success"] is True
            assert result["version"] == "3.0.10.1567"
            assert result["response_time_ms"] is not None
            assert result["error"] is None

    @pytest.mark.asyncio
    async def test_failed_connection_test(self):
        """Test failed connection test."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        with patch.object(client, "_request") as mock_request:
            mock_request.side_effect = SonarrConnectionError("Connection refused")

            result = await client.test_connection()

            assert result["success"] is False
            assert result["version"] is None
            assert result["response_time_ms"] is None
            assert "Connection refused" in result["error"]


class TestSonarrAPIRequests:
    """Test API request methods."""

    @pytest.mark.asyncio
    async def test_get_system_status(self):
        """Test system status endpoint."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        expected_response = {
            "version": "3.0.10.1567",
            "instanceName": "Test Sonarr",
        }

        with patch.object(client, "_request") as mock_request:
            mock_request.return_value = expected_response

            result = await client.get_system_status()

            assert result == expected_response
            mock_request.assert_called_once_with("GET", "/api/v3/system/status")

    @pytest.mark.asyncio
    async def test_get_wanted_missing(self):
        """Test wanted/missing endpoint."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        expected_response = {
            "page": 1,
            "pageSize": 50,
            "totalRecords": 100,
            "records": [],
        }

        with patch.object(client, "_request") as mock_request:
            mock_request.return_value = expected_response

            result = await client.get_wanted_missing(page=1, page_size=50)

            assert result == expected_response
            mock_request.assert_called_once_with(
                "GET",
                "/api/v3/wanted/missing",
                params={
                    "page": 1,
                    "pageSize": 50,
                    "sortKey": "airDateUtc",
                    "sortDirection": "descending",
                },
            )

    @pytest.mark.asyncio
    async def test_get_wanted_cutoff(self):
        """Test wanted/cutoff endpoint."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        expected_response = {
            "page": 1,
            "pageSize": 50,
            "totalRecords": 50,
            "records": [],
        }

        with patch.object(client, "_request") as mock_request:
            mock_request.return_value = expected_response

            result = await client.get_wanted_cutoff(page=1, page_size=50)

            assert result == expected_response
            mock_request.assert_called_once_with(
                "GET",
                "/api/v3/wanted/cutoff",
                params={
                    "page": 1,
                    "pageSize": 50,
                    "sortKey": "airDateUtc",
                    "sortDirection": "descending",
                },
            )

    @pytest.mark.asyncio
    async def test_search_episodes(self):
        """Test episode search command."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        expected_response = {
            "id": 12345,
            "name": "EpisodeSearch",
            "status": "queued",
        }

        with patch.object(client, "_request") as mock_request:
            mock_request.return_value = expected_response

            result = await client.search_episodes([1, 2, 3])

            assert result == expected_response
            mock_request.assert_called_once_with(
                "POST",
                "/api/v3/command",
                json={
                    "name": "EpisodeSearch",
                    "episodeIds": [1, 2, 3],
                },
            )

    @pytest.mark.asyncio
    async def test_search_episodes_empty_list(self):
        """Test episode search with empty episode list."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        with pytest.raises(ValueError, match="episode_ids cannot be empty"):
            await client.search_episodes([])

    @pytest.mark.asyncio
    async def test_search_series(self):
        """Test series search command."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        expected_response = {
            "id": 67890,
            "name": "SeriesSearch",
            "status": "queued",
        }

        with patch.object(client, "_request") as mock_request:
            mock_request.return_value = expected_response

            result = await client.search_series(42)

            assert result == expected_response
            mock_request.assert_called_once_with(
                "POST",
                "/api/v3/command",
                json={
                    "name": "SeriesSearch",
                    "seriesId": 42,
                },
            )

    @pytest.mark.asyncio
    async def test_get_quality_profiles(self):
        """Test quality profiles endpoint."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        expected_response = [
            {"id": 1, "name": "HD-1080p"},
            {"id": 2, "name": "HD-720p"},
        ]

        with patch.object(client, "_request") as mock_request:
            mock_request.return_value = expected_response

            result = await client.get_quality_profiles()

            assert result == expected_response
            mock_request.assert_called_once_with("GET", "/api/v3/qualityprofile")

    @pytest.mark.asyncio
    async def test_get_series_by_id(self):
        """Test get series by ID."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        expected_response = {
            "id": 1,
            "title": "Test Series",
        }

        with patch.object(client, "_request") as mock_request:
            mock_request.return_value = expected_response

            result = await client.get_series(series_id=1)

            assert result == expected_response
            mock_request.assert_called_once_with("GET", "/api/v3/series/1")

    @pytest.mark.asyncio
    async def test_get_all_series(self):
        """Test get all series."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        expected_response = [
            {"id": 1, "title": "Series 1"},
            {"id": 2, "title": "Series 2"},
        ]

        with patch.object(client, "_request") as mock_request:
            mock_request.return_value = expected_response

            result = await client.get_series()

            assert result == expected_response
            mock_request.assert_called_once_with("GET", "/api/v3/series")

    @pytest.mark.asyncio
    async def test_get_command_status(self):
        """Test command status endpoint."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        expected_response = {
            "id": 12345,
            "status": "completed",
        }

        with patch.object(client, "_request") as mock_request:
            mock_request.return_value = expected_response

            result = await client.get_command_status(12345)

            assert result == expected_response
            mock_request.assert_called_once_with("GET", "/api/v3/command/12345")


class TestSonarrErrorHandling:
    """Test error handling and exceptions."""

    @pytest.mark.asyncio
    async def test_authentication_error(self):
        """Test handling of authentication errors."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        with patch.object(client, "_ensure_client", new_callable=AsyncMock):
            with patch.object(client, "_rate_limit", new_callable=AsyncMock):
                client._client = AsyncMock()
                client._client.request = AsyncMock(return_value=mock_response)

                with pytest.raises(SonarrAuthenticationError, match="Invalid API key"):
                    await client._request("GET", "/api/v3/system/status")

    @pytest.mark.asyncio
    async def test_rate_limit_error(self):
        """Test handling of rate limit errors."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Too Many Requests"

        with patch.object(client, "_ensure_client", new_callable=AsyncMock):
            with patch.object(client, "_rate_limit", new_callable=AsyncMock):
                client._client = AsyncMock()
                client._client.request = AsyncMock(return_value=mock_response)

                with pytest.raises(SonarrRateLimitError, match="Rate limit exceeded"):
                    await client._request("GET", "/api/v3/system/status")

    @pytest.mark.asyncio
    async def test_client_error_4xx(self):
        """Test handling of client errors (4xx)."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"

        with patch.object(client, "_ensure_client", new_callable=AsyncMock):
            with patch.object(client, "_rate_limit", new_callable=AsyncMock):
                client._client = AsyncMock()
                client._client.request = AsyncMock(return_value=mock_response)

                with pytest.raises(SonarrAPIError, match="Client error"):
                    await client._request("GET", "/api/v3/system/status")

    @pytest.mark.asyncio
    async def test_server_error_5xx(self):
        """Test handling of server errors (5xx)."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch.object(client, "_ensure_client", new_callable=AsyncMock):
            with patch.object(client, "_rate_limit", new_callable=AsyncMock):
                client._client = AsyncMock()
                client._client.request = AsyncMock(return_value=mock_response)

                with pytest.raises(SonarrAPIError, match="Server error"):
                    await client._request("GET", "/api/v3/system/status")

    @pytest.mark.asyncio
    async def test_connection_error(self):
        """Test handling of connection errors."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        with patch.object(client, "_ensure_client", new_callable=AsyncMock):
            with patch.object(client, "_rate_limit", new_callable=AsyncMock):
                client._client = AsyncMock()
                client._client.request = AsyncMock(
                    side_effect=httpx.ConnectError("Connection refused")
                )

                with pytest.raises(SonarrConnectionError, match="Failed to connect"):
                    await client._request("GET", "/api/v3/system/status")

    @pytest.mark.asyncio
    async def test_timeout_error(self):
        """Test handling of timeout errors."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        with patch.object(client, "_ensure_client", new_callable=AsyncMock):
            with patch.object(client, "_rate_limit", new_callable=AsyncMock):
                client._client = AsyncMock()
                client._client.request = AsyncMock(
                    side_effect=httpx.TimeoutException("Request timeout")
                )

                with pytest.raises(SonarrConnectionError, match="Request timeout"):
                    await client._request("GET", "/api/v3/system/status")


class TestSonarrRetryLogic:
    """Test retry logic with exponential backoff."""

    @pytest.mark.asyncio
    async def test_retry_on_connection_error(self):
        """Test retry on connection errors."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        # Mock successful response on third attempt
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"version": "3.0.0"}

        call_count = 0

        async def mock_request_with_retries(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.ConnectError("Connection refused")
            return mock_response

        with patch.object(client, "_ensure_client", new_callable=AsyncMock):
            with patch.object(client, "_rate_limit", new_callable=AsyncMock):
                client._client = AsyncMock()
                client._client.request = mock_request_with_retries

                result = await client._request("GET", "/api/v3/system/status")

                assert result == {"version": "3.0.0"}
                assert call_count == 3  # Should retry twice before succeeding

    @pytest.mark.asyncio
    async def test_retry_exhausted(self):
        """Test behavior when retries are exhausted."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        with patch.object(client, "_ensure_client", new_callable=AsyncMock):
            with patch.object(client, "_rate_limit", new_callable=AsyncMock):
                client._client = AsyncMock()
                # Always fail
                client._client.request = AsyncMock(
                    side_effect=httpx.ConnectError("Connection refused")
                )

                # Should raise after max retries
                with pytest.raises(SonarrConnectionError):
                    await client._request("GET", "/api/v3/system/status")
