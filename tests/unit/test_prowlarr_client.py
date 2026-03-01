"""
Unit tests for Prowlarr API client.

Tests cover:
- Client initialization and class attributes
- Indexer retrieval with rate limit field parsing
- Application retrieval with BaseUrl parsing
- Indexer stats retrieval keyed by indexer ID
- Indexer status (circuit-breaker) retrieval
- Handling of missing/incomplete nested fields
"""

from unittest.mock import AsyncMock, patch

import pytest

from splintarr.services.prowlarr import (
    ProwlarrAPIError,
    ProwlarrAuthenticationError,
    ProwlarrClient,
    ProwlarrConnectionError,
    ProwlarrError,
    ProwlarrRateLimitError,
)


@pytest.fixture
def client() -> ProwlarrClient:
    """Create a ProwlarrClient instance for testing."""
    return ProwlarrClient(
        url="https://prowlarr.example.com",
        api_key="a" * 32,
    )


class TestProwlarrClientInitialization:
    """Test Prowlarr client initialization and class attributes."""

    def test_service_name(self, client: ProwlarrClient) -> None:
        """Test that service_name is set to prowlarr."""
        assert client.service_name == "prowlarr"

    def test_error_classes_assigned(self, client: ProwlarrClient) -> None:
        """Test that error class attributes point to Prowlarr-specific exceptions."""
        assert client._error_base is ProwlarrError
        assert client._error_connection is ProwlarrConnectionError
        assert client._error_auth is ProwlarrAuthenticationError
        assert client._error_api is ProwlarrAPIError
        assert client._error_rate is ProwlarrRateLimitError

    def test_exception_hierarchy(self) -> None:
        """Test that Prowlarr exceptions inherit correctly."""
        from splintarr.services.base_client import (
            ArrAPIError,
            ArrAuthenticationError,
            ArrClientError,
            ArrConnectionError,
            ArrRateLimitError,
        )

        assert issubclass(ProwlarrError, ArrClientError)
        assert issubclass(ProwlarrConnectionError, ProwlarrError)
        assert issubclass(ProwlarrConnectionError, ArrConnectionError)
        assert issubclass(ProwlarrAuthenticationError, ProwlarrError)
        assert issubclass(ProwlarrAuthenticationError, ArrAuthenticationError)
        assert issubclass(ProwlarrAPIError, ProwlarrError)
        assert issubclass(ProwlarrAPIError, ArrAPIError)
        assert issubclass(ProwlarrRateLimitError, ProwlarrError)
        assert issubclass(ProwlarrRateLimitError, ArrRateLimitError)

    def test_valid_initialization(self) -> None:
        """Test successful client initialization with standard args."""
        c = ProwlarrClient(
            url="https://prowlarr.example.com",
            api_key="a" * 32,
            verify_ssl=False,
            timeout=60,
            rate_limit_per_second=2.0,
        )
        assert c.url == "https://prowlarr.example.com"
        assert c.api_key == "a" * 32
        assert c.verify_ssl is False
        assert c.timeout == 60
        assert c.rate_limit_per_second == 2.0


class TestGetIndexers:
    """Test get_indexers method."""

    @pytest.mark.asyncio
    async def test_get_indexers_parses_limits(self, client: ProwlarrClient) -> None:
        """Verify QueryLimit/GrabLimit/LimitsUnit extraction from nested fields."""
        api_response = [
            {
                "id": 1,
                "name": "NZBgeek",
                "enable": True,
                "protocol": "usenet",
                "tags": [1, 2],
                "fields": [
                    {"name": "QueryLimit", "value": 100},
                    {"name": "GrabLimit", "value": 50},
                    {"name": "LimitsUnit", "value": 1},  # 1 = Hour
                    {"name": "BaseUrl", "value": "https://nzbgeek.info"},
                ],
            },
            {
                "id": 2,
                "name": "1337x",
                "enable": True,
                "protocol": "torrent",
                "tags": [],
                "fields": [
                    {"name": "QueryLimit", "value": 200},
                    {"name": "GrabLimit", "value": 75},
                    {"name": "LimitsUnit", "value": 0},  # 0 = Day
                ],
            },
        ]

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = api_response

            result = await client.get_indexers()

            mock_req.assert_called_once_with("GET", "/api/v1/indexer")
            assert len(result) == 2

            # First indexer — hourly limits
            assert result[0]["id"] == 1
            assert result[0]["name"] == "NZBgeek"
            assert result[0]["enable"] is True
            assert result[0]["protocol"] == "usenet"
            assert result[0]["query_limit"] == 100
            assert result[0]["grab_limit"] == 50
            assert result[0]["limits_unit"] == "hour"
            assert result[0]["tags"] == [1, 2]

            # Second indexer — daily limits
            assert result[1]["id"] == 2
            assert result[1]["query_limit"] == 200
            assert result[1]["grab_limit"] == 75
            assert result[1]["limits_unit"] == "day"

    @pytest.mark.asyncio
    async def test_get_indexers_handles_missing_fields(self, client: ProwlarrClient) -> None:
        """No fields array results in None for limit values."""
        api_response = [
            {
                "id": 3,
                "name": "NoFieldsIndexer",
                "enable": False,
                "protocol": "torrent",
                "tags": [],
                # No "fields" key at all
            },
        ]

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = api_response

            result = await client.get_indexers()

            assert len(result) == 1
            assert result[0]["id"] == 3
            assert result[0]["name"] == "NoFieldsIndexer"
            assert result[0]["query_limit"] is None
            assert result[0]["grab_limit"] is None
            assert result[0]["limits_unit"] is None

    @pytest.mark.asyncio
    async def test_get_indexers_handles_empty_fields(self, client: ProwlarrClient) -> None:
        """Empty fields array results in None for limit values."""
        api_response = [
            {
                "id": 4,
                "name": "EmptyFieldsIndexer",
                "enable": True,
                "protocol": "usenet",
                "tags": [3],
                "fields": [],
            },
        ]

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = api_response

            result = await client.get_indexers()

            assert result[0]["query_limit"] is None
            assert result[0]["grab_limit"] is None
            assert result[0]["limits_unit"] is None

    @pytest.mark.asyncio
    async def test_get_indexers_parses_disabled_till(self, client: ProwlarrClient) -> None:
        """Verify disabled_till is extracted if present on the indexer."""
        api_response = [
            {
                "id": 5,
                "name": "DisabledIndexer",
                "enable": True,
                "protocol": "torrent",
                "tags": [],
                "fields": [],
                "disabledTill": "2026-03-01T12:00:00Z",
            },
        ]

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = api_response

            result = await client.get_indexers()

            assert result[0]["disabled_till"] == "2026-03-01T12:00:00Z"

    @pytest.mark.asyncio
    async def test_get_indexers_no_disabled_till(self, client: ProwlarrClient) -> None:
        """Verify disabled_till is None when not present."""
        api_response = [
            {
                "id": 6,
                "name": "ActiveIndexer",
                "enable": True,
                "protocol": "usenet",
                "tags": [],
                "fields": [],
            },
        ]

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = api_response

            result = await client.get_indexers()

            assert result[0]["disabled_till"] is None


class TestGetApplications:
    """Test get_applications method."""

    @pytest.mark.asyncio
    async def test_get_applications(self, client: ProwlarrClient) -> None:
        """Verify BaseUrl parsing from nested fields."""
        api_response = [
            {
                "id": 10,
                "name": "Sonarr",
                "implementation": "Sonarr",
                "tags": [1],
                "fields": [
                    {"name": "ProwlarrUrl", "value": "https://prowlarr.local"},
                    {"name": "BaseUrl", "value": "https://sonarr.local:8989"},
                    {"name": "ApiKey", "value": "some-api-key"},
                ],
            },
            {
                "id": 11,
                "name": "Radarr",
                "implementation": "Radarr",
                "tags": [],
                "fields": [
                    {"name": "BaseUrl", "value": "https://radarr.local:7878"},
                ],
            },
        ]

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = api_response

            result = await client.get_applications()

            mock_req.assert_called_once_with("GET", "/api/v1/applications")
            assert len(result) == 2

            assert result[0]["id"] == 10
            assert result[0]["name"] == "Sonarr"
            assert result[0]["implementation"] == "Sonarr"
            assert result[0]["base_url"] == "https://sonarr.local:8989"
            assert result[0]["tags"] == [1]

            assert result[1]["id"] == 11
            assert result[1]["name"] == "Radarr"
            assert result[1]["implementation"] == "Radarr"
            assert result[1]["base_url"] == "https://radarr.local:7878"
            assert result[1]["tags"] == []

    @pytest.mark.asyncio
    async def test_get_applications_missing_base_url(self, client: ProwlarrClient) -> None:
        """Application with no BaseUrl in fields returns None for base_url."""
        api_response = [
            {
                "id": 12,
                "name": "Other",
                "implementation": "Lidarr",
                "tags": [],
                "fields": [
                    {"name": "ApiKey", "value": "abc123"},
                ],
            },
        ]

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = api_response

            result = await client.get_applications()

            assert result[0]["base_url"] is None

    @pytest.mark.asyncio
    async def test_get_applications_no_fields(self, client: ProwlarrClient) -> None:
        """Application with no fields array returns None for base_url."""
        api_response = [
            {
                "id": 13,
                "name": "NoFields",
                "implementation": "Readarr",
                "tags": [],
            },
        ]

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = api_response

            result = await client.get_applications()

            assert result[0]["base_url"] is None


class TestGetIndexerStats:
    """Test get_indexer_stats method."""

    @pytest.mark.asyncio
    async def test_get_indexer_stats(self, client: ProwlarrClient) -> None:
        """Verify keyed-by-id return format with correct field mapping."""
        api_response = {
            "indexers": [
                {
                    "indexerId": 1,
                    "indexerName": "NZBgeek",
                    "numberOfQueries": 450,
                    "numberOfGrabs": 30,
                    "numberOfFailedQueries": 5,
                },
                {
                    "indexerId": 2,
                    "indexerName": "1337x",
                    "numberOfQueries": 200,
                    "numberOfGrabs": 15,
                    "numberOfFailedQueries": 0,
                },
            ],
        }

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = api_response

            result = await client.get_indexer_stats(hours=24)

            # Verify the request was made with date range params
            mock_req.assert_called_once()
            call_args = mock_req.call_args
            assert call_args[0][0] == "GET"
            assert call_args[0][1] == "/api/v1/indexerstats"
            params = (
                call_args[1].get("params") or call_args[0][2]
                if len(call_args[0]) > 2
                else call_args[1].get("params")
            )
            assert "startDate" in params
            assert "endDate" in params

            # Verify keyed-by-id format
            assert 1 in result
            assert 2 in result

            assert result[1]["name"] == "NZBgeek"
            assert result[1]["queries"] == 450
            assert result[1]["grabs"] == 30
            assert result[1]["failed_queries"] == 5

            assert result[2]["name"] == "1337x"
            assert result[2]["queries"] == 200
            assert result[2]["grabs"] == 15
            assert result[2]["failed_queries"] == 0

    @pytest.mark.asyncio
    async def test_get_indexer_stats_custom_hours(self, client: ProwlarrClient) -> None:
        """Verify custom hours parameter affects date range."""
        api_response = {"indexers": []}

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = api_response

            result = await client.get_indexer_stats(hours=48)

            call_args = mock_req.call_args
            params = (
                call_args[1].get("params") or call_args[0][2]
                if len(call_args[0]) > 2
                else call_args[1].get("params")
            )
            assert "startDate" in params
            assert "endDate" in params

            # Result should be empty dict for no indexers
            assert result == {}

    @pytest.mark.asyncio
    async def test_get_indexer_stats_empty_response(self, client: ProwlarrClient) -> None:
        """Verify empty indexers list returns empty dict."""
        api_response = {"indexers": []}

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = api_response

            result = await client.get_indexer_stats()

            assert result == {}


class TestGetIndexerStatus:
    """Test get_indexer_status method."""

    @pytest.mark.asyncio
    async def test_get_indexer_status(self, client: ProwlarrClient) -> None:
        """Verify circuit-breaker status parsing."""
        api_response = [
            {
                "indexerId": 1,
                "disabledTill": "2026-03-01T15:30:00Z",
            },
            {
                "indexerId": 3,
                "disabledTill": "2026-03-02T00:00:00Z",
            },
        ]

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = api_response

            result = await client.get_indexer_status()

            mock_req.assert_called_once_with("GET", "/api/v1/indexerstatus")
            assert len(result) == 2

            assert result[0]["indexer_id"] == 1
            assert result[0]["disabled_till"] == "2026-03-01T15:30:00Z"

            assert result[1]["indexer_id"] == 3
            assert result[1]["disabled_till"] == "2026-03-02T00:00:00Z"

    @pytest.mark.asyncio
    async def test_get_indexer_status_empty(self, client: ProwlarrClient) -> None:
        """Verify empty status list when no indexers are disabled."""
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = []

            result = await client.get_indexer_status()

            assert result == []

    @pytest.mark.asyncio
    async def test_get_indexer_status_no_disabled_till(self, client: ProwlarrClient) -> None:
        """Verify handling when disabledTill is not present."""
        api_response = [
            {
                "indexerId": 5,
            },
        ]

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = api_response

            result = await client.get_indexer_status()

            assert result[0]["indexer_id"] == 5
            assert result[0]["disabled_till"] is None
