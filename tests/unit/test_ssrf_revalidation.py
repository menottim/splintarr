"""
Unit tests for SSRF re-validation in Sonarr and Radarr HTTP clients.

Verifies that validate_instance_url() is called immediately before each
outbound HTTP request in _request(), preventing DNS rebinding attacks
(TOCTOU: DNS may resolve to a different IP between initial validation
and actual request time).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from splintarr.core.ssrf_protection import SSRFError
from splintarr.services.radarr import RadarrClient, RadarrConnectionError
from splintarr.services.sonarr import SonarrClient, SonarrConnectionError


# ---------------------------------------------------------------------------
# Sonarr client SSRF re-validation tests
# ---------------------------------------------------------------------------


class TestSonarrSSRFRevalidation:
    """Verify SSRF re-validation happens on every Sonarr _request() call."""

    def _make_client(self) -> SonarrClient:
        return SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

    @pytest.mark.asyncio
    async def test_validate_instance_url_called_before_request(self):
        """validate_instance_url must be called during _request()."""
        client = self._make_client()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"version": "3.0.0"}

        with (
            patch.object(client, "_ensure_client", new_callable=AsyncMock),
            patch.object(client, "_rate_limit", new_callable=AsyncMock),
            patch(
                "splintarr.services.sonarr.validate_instance_url"
            ) as mock_validate,
        ):
            client._client = AsyncMock()
            client._client.request = AsyncMock(return_value=mock_response)

            await client._request("GET", "/api/v3/system/status")

            mock_validate.assert_called_once_with(
                "https://sonarr.example.com",
                allow_local=True,  # conftest sets ALLOW_LOCAL_INSTANCES=true
            )

    @pytest.mark.asyncio
    async def test_ssrf_error_raises_connection_error(self):
        """SSRFError from re-validation must surface as SonarrConnectionError."""
        client = self._make_client()

        with (
            patch.object(client, "_ensure_client", new_callable=AsyncMock),
            patch.object(client, "_rate_limit", new_callable=AsyncMock),
            patch(
                "splintarr.services.sonarr.validate_instance_url",
                side_effect=SSRFError("URL resolves to blocked network: 10.0.0.0/8"),
            ),
        ):
            client._client = AsyncMock()

            with pytest.raises(SonarrConnectionError, match="SSRF protection blocked"):
                await client._request("GET", "/api/v3/system/status")

    @pytest.mark.asyncio
    async def test_ssrf_error_prevents_http_request(self):
        """When SSRF re-validation fails, no HTTP request must be made."""
        client = self._make_client()

        with (
            patch.object(client, "_ensure_client", new_callable=AsyncMock),
            patch.object(client, "_rate_limit", new_callable=AsyncMock),
            patch(
                "splintarr.services.sonarr.validate_instance_url",
                side_effect=SSRFError("blocked"),
            ),
        ):
            mock_http = AsyncMock()
            client._client = AsyncMock()
            client._client.request = mock_http

            with pytest.raises(SonarrConnectionError):
                await client._request("GET", "/api/v3/system/status")

            mock_http.assert_not_called()

    @pytest.mark.asyncio
    async def test_ssrf_error_not_retried(self):
        """SSRF failures must not be retried by the @retry decorator."""
        client = self._make_client()
        call_count = 0

        def counting_validate(url: str, allow_local: bool = False) -> None:
            nonlocal call_count
            call_count += 1
            raise SSRFError("blocked")

        with (
            patch.object(client, "_ensure_client", new_callable=AsyncMock),
            patch.object(client, "_rate_limit", new_callable=AsyncMock),
            patch(
                "splintarr.services.sonarr.validate_instance_url",
                side_effect=counting_validate,
            ),
        ):
            client._client = AsyncMock()

            with pytest.raises(SonarrConnectionError):
                await client._request("GET", "/api/v3/system/status")

            # Should be called exactly once -- no retries for SSRF errors
            assert call_count == 1

    @pytest.mark.asyncio
    async def test_revalidation_on_every_request(self):
        """validate_instance_url must be invoked on every _request() call."""
        client = self._make_client()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok"}

        with (
            patch.object(client, "_ensure_client", new_callable=AsyncMock),
            patch.object(client, "_rate_limit", new_callable=AsyncMock),
            patch(
                "splintarr.services.sonarr.validate_instance_url"
            ) as mock_validate,
        ):
            client._client = AsyncMock()
            client._client.request = AsyncMock(return_value=mock_response)

            await client._request("GET", "/api/v3/system/status")
            await client._request("GET", "/api/v3/series")
            await client._request("POST", "/api/v3/command", json={"name": "test"})

            assert mock_validate.call_count == 3

    @pytest.mark.asyncio
    async def test_ssrf_error_preserves_cause(self):
        """The original SSRFError must be chained as __cause__."""
        client = self._make_client()
        original = SSRFError("blocked network")

        with (
            patch.object(client, "_ensure_client", new_callable=AsyncMock),
            patch.object(client, "_rate_limit", new_callable=AsyncMock),
            patch(
                "splintarr.services.sonarr.validate_instance_url",
                side_effect=original,
            ),
        ):
            client._client = AsyncMock()

            with pytest.raises(SonarrConnectionError) as exc_info:
                await client._request("GET", "/api/v3/system/status")

            assert exc_info.value.__cause__ is original


# ---------------------------------------------------------------------------
# Radarr client SSRF re-validation tests
# ---------------------------------------------------------------------------


class TestRadarrSSRFRevalidation:
    """Verify SSRF re-validation happens on every Radarr _request() call."""

    def _make_client(self) -> RadarrClient:
        return RadarrClient(
            url="https://radarr.example.com",
            api_key="a" * 32,
        )

    @pytest.mark.asyncio
    async def test_validate_instance_url_called_before_request(self):
        """validate_instance_url must be called during _request()."""
        client = self._make_client()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"version": "3.2.0"}

        with (
            patch.object(client, "_ensure_client", new_callable=AsyncMock),
            patch.object(client, "_rate_limit", new_callable=AsyncMock),
            patch(
                "splintarr.services.radarr.validate_instance_url"
            ) as mock_validate,
        ):
            client._client = AsyncMock()
            client._client.request = AsyncMock(return_value=mock_response)

            await client._request("GET", "/api/v3/system/status")

            mock_validate.assert_called_once_with(
                "https://radarr.example.com",
                allow_local=True,
            )

    @pytest.mark.asyncio
    async def test_ssrf_error_raises_connection_error(self):
        """SSRFError from re-validation must surface as RadarrConnectionError."""
        client = self._make_client()

        with (
            patch.object(client, "_ensure_client", new_callable=AsyncMock),
            patch.object(client, "_rate_limit", new_callable=AsyncMock),
            patch(
                "splintarr.services.radarr.validate_instance_url",
                side_effect=SSRFError("URL resolves to blocked network: 10.0.0.0/8"),
            ),
        ):
            client._client = AsyncMock()

            with pytest.raises(RadarrConnectionError, match="SSRF protection blocked"):
                await client._request("GET", "/api/v3/system/status")

    @pytest.mark.asyncio
    async def test_ssrf_error_prevents_http_request(self):
        """When SSRF re-validation fails, no HTTP request must be made."""
        client = self._make_client()

        with (
            patch.object(client, "_ensure_client", new_callable=AsyncMock),
            patch.object(client, "_rate_limit", new_callable=AsyncMock),
            patch(
                "splintarr.services.radarr.validate_instance_url",
                side_effect=SSRFError("blocked"),
            ),
        ):
            mock_http = AsyncMock()
            client._client = AsyncMock()
            client._client.request = mock_http

            with pytest.raises(RadarrConnectionError):
                await client._request("GET", "/api/v3/system/status")

            mock_http.assert_not_called()

    @pytest.mark.asyncio
    async def test_ssrf_error_not_retried(self):
        """SSRF failures must not be retried by the @retry decorator."""
        client = self._make_client()
        call_count = 0

        def counting_validate(url: str, allow_local: bool = False) -> None:
            nonlocal call_count
            call_count += 1
            raise SSRFError("blocked")

        with (
            patch.object(client, "_ensure_client", new_callable=AsyncMock),
            patch.object(client, "_rate_limit", new_callable=AsyncMock),
            patch(
                "splintarr.services.radarr.validate_instance_url",
                side_effect=counting_validate,
            ),
        ):
            client._client = AsyncMock()

            with pytest.raises(RadarrConnectionError):
                await client._request("GET", "/api/v3/system/status")

            assert call_count == 1

    @pytest.mark.asyncio
    async def test_revalidation_on_every_request(self):
        """validate_instance_url must be invoked on every _request() call."""
        client = self._make_client()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok"}

        with (
            patch.object(client, "_ensure_client", new_callable=AsyncMock),
            patch.object(client, "_rate_limit", new_callable=AsyncMock),
            patch(
                "splintarr.services.radarr.validate_instance_url"
            ) as mock_validate,
        ):
            client._client = AsyncMock()
            client._client.request = AsyncMock(return_value=mock_response)

            await client._request("GET", "/api/v3/system/status")
            await client._request("GET", "/api/v3/movie")
            await client._request("POST", "/api/v3/command", json={"name": "test"})

            assert mock_validate.call_count == 3

    @pytest.mark.asyncio
    async def test_ssrf_error_preserves_cause(self):
        """The original SSRFError must be chained as __cause__."""
        client = self._make_client()
        original = SSRFError("blocked network")

        with (
            patch.object(client, "_ensure_client", new_callable=AsyncMock),
            patch.object(client, "_rate_limit", new_callable=AsyncMock),
            patch(
                "splintarr.services.radarr.validate_instance_url",
                side_effect=original,
            ),
        ):
            client._client = AsyncMock()

            with pytest.raises(RadarrConnectionError) as exc_info:
                await client._request("GET", "/api/v3/system/status")

            assert exc_info.value.__cause__ is original
