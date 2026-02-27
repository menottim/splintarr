"""
Unit tests for API key redirect protection (GitHub issue #16).

Verifies that Sonarr and Radarr clients:
- Do NOT follow HTTP redirects (prevents X-Api-Key leaking to redirect targets)
- Raise connection errors with helpful messages when a redirect is received
- Include the redirect Location header in the error message
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from splintarr.services.radarr import RadarrClient, RadarrConnectionError
from splintarr.services.sonarr import SonarrClient, SonarrConnectionError


class TestSonarrRedirectProtection:
    """Test that Sonarr client does not follow redirects (API key leak prevention)."""

    @pytest.mark.asyncio
    async def test_client_created_with_follow_redirects_false(self):
        """Test that httpx.AsyncClient is created with follow_redirects=False."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        await client._ensure_client()

        assert client._client is not None
        assert client._client.follow_redirects is False

        await client.close()

    @pytest.mark.asyncio
    async def test_301_redirect_raises_connection_error(self):
        """Test that a 301 Moved Permanently raises SonarrConnectionError."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        mock_response = MagicMock()
        mock_response.status_code = 301
        mock_response.headers = {"Location": "https://evil.example.com/api/v3/system/status"}

        with patch.object(client, "_ensure_client", new_callable=AsyncMock):
            with patch.object(client, "_rate_limit", new_callable=AsyncMock):
                client._client = AsyncMock()
                client._client.request = AsyncMock(return_value=mock_response)

                with pytest.raises(SonarrConnectionError, match="redirect.*301") as exc_info:
                    await client._request("GET", "/api/v3/system/status")

                assert "evil.example.com" in str(exc_info.value)
                assert "Check the instance URL configuration" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_302_redirect_raises_connection_error(self):
        """Test that a 302 Found raises SonarrConnectionError."""
        client = SonarrClient(
            url="http://sonarr.example.com",
            api_key="a" * 32,
        )

        mock_response = MagicMock()
        mock_response.status_code = 302
        mock_response.headers = {"Location": "https://sonarr.example.com/api/v3/system/status"}

        with patch.object(client, "_ensure_client", new_callable=AsyncMock):
            with patch.object(client, "_rate_limit", new_callable=AsyncMock):
                client._client = AsyncMock()
                client._client.request = AsyncMock(return_value=mock_response)

                with pytest.raises(SonarrConnectionError, match="redirect.*302"):
                    await client._request("GET", "/api/v3/system/status")

    @pytest.mark.asyncio
    async def test_307_redirect_raises_connection_error(self):
        """Test that a 307 Temporary Redirect raises SonarrConnectionError."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        mock_response = MagicMock()
        mock_response.status_code = 307
        mock_response.headers = {"Location": "https://other.example.com/"}

        with patch.object(client, "_ensure_client", new_callable=AsyncMock):
            with patch.object(client, "_rate_limit", new_callable=AsyncMock):
                client._client = AsyncMock()
                client._client.request = AsyncMock(return_value=mock_response)

                with pytest.raises(SonarrConnectionError, match="redirect.*307"):
                    await client._request("GET", "/api/v3/system/status")

    @pytest.mark.asyncio
    async def test_308_redirect_raises_connection_error(self):
        """Test that a 308 Permanent Redirect raises SonarrConnectionError."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        mock_response = MagicMock()
        mock_response.status_code = 308
        mock_response.headers = {"Location": "https://new.example.com/sonarr/"}

        with patch.object(client, "_ensure_client", new_callable=AsyncMock):
            with patch.object(client, "_rate_limit", new_callable=AsyncMock):
                client._client = AsyncMock()
                client._client.request = AsyncMock(return_value=mock_response)

                with pytest.raises(SonarrConnectionError, match="redirect.*308"):
                    await client._request("GET", "/api/v3/system/status")

    @pytest.mark.asyncio
    async def test_redirect_missing_location_header(self):
        """Test redirect handling when Location header is absent."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        mock_response = MagicMock()
        mock_response.status_code = 301
        mock_response.headers = {}  # No Location header

        with patch.object(client, "_ensure_client", new_callable=AsyncMock):
            with patch.object(client, "_rate_limit", new_callable=AsyncMock):
                client._client = AsyncMock()
                client._client.request = AsyncMock(return_value=mock_response)

                with pytest.raises(SonarrConnectionError, match="unknown"):
                    await client._request("GET", "/api/v3/system/status")

    @pytest.mark.asyncio
    async def test_redirect_does_not_leak_api_key(self):
        """Test that API key is NOT sent to redirect destination.

        Since follow_redirects=False, the client never makes a second request.
        We verify only one request was made (the original), and it raised an error.
        """
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        mock_response = MagicMock()
        mock_response.status_code = 302
        mock_response.headers = {"Location": "https://attacker.example.com/steal-key"}

        with patch.object(client, "_ensure_client", new_callable=AsyncMock):
            with patch.object(client, "_rate_limit", new_callable=AsyncMock):
                mock_request = AsyncMock(return_value=mock_response)
                client._client = AsyncMock()
                client._client.request = mock_request

                with pytest.raises(SonarrConnectionError):
                    await client._request("GET", "/api/v3/system/status")

                # Verify only ONE request was made (no follow-up to redirect target)
                assert mock_request.call_count == 1


class TestRadarrRedirectProtection:
    """Test that Radarr client does not follow redirects (API key leak prevention)."""

    @pytest.mark.asyncio
    async def test_client_created_with_follow_redirects_false(self):
        """Test that httpx.AsyncClient is created with follow_redirects=False."""
        client = RadarrClient(
            url="https://radarr.example.com",
            api_key="a" * 32,
        )

        await client._ensure_client()

        assert client._client is not None
        assert client._client.follow_redirects is False

        await client.close()

    @pytest.mark.asyncio
    async def test_301_redirect_raises_connection_error(self):
        """Test that a 301 Moved Permanently raises RadarrConnectionError."""
        client = RadarrClient(
            url="https://radarr.example.com",
            api_key="a" * 32,
        )

        mock_response = MagicMock()
        mock_response.status_code = 301
        mock_response.headers = {"Location": "https://evil.example.com/api/v3/system/status"}

        with patch.object(client, "_ensure_client", new_callable=AsyncMock):
            with patch.object(client, "_rate_limit", new_callable=AsyncMock):
                client._client = AsyncMock()
                client._client.request = AsyncMock(return_value=mock_response)

                with pytest.raises(RadarrConnectionError, match="redirect.*301") as exc_info:
                    await client._request("GET", "/api/v3/system/status")

                assert "evil.example.com" in str(exc_info.value)
                assert "Check the instance URL configuration" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_302_redirect_raises_connection_error(self):
        """Test that a 302 Found raises RadarrConnectionError."""
        client = RadarrClient(
            url="http://radarr.example.com",
            api_key="a" * 32,
        )

        mock_response = MagicMock()
        mock_response.status_code = 302
        mock_response.headers = {"Location": "https://radarr.example.com/api/v3/system/status"}

        with patch.object(client, "_ensure_client", new_callable=AsyncMock):
            with patch.object(client, "_rate_limit", new_callable=AsyncMock):
                client._client = AsyncMock()
                client._client.request = AsyncMock(return_value=mock_response)

                with pytest.raises(RadarrConnectionError, match="redirect.*302"):
                    await client._request("GET", "/api/v3/system/status")

    @pytest.mark.asyncio
    async def test_307_redirect_raises_connection_error(self):
        """Test that a 307 Temporary Redirect raises RadarrConnectionError."""
        client = RadarrClient(
            url="https://radarr.example.com",
            api_key="a" * 32,
        )

        mock_response = MagicMock()
        mock_response.status_code = 307
        mock_response.headers = {"Location": "https://other.example.com/"}

        with patch.object(client, "_ensure_client", new_callable=AsyncMock):
            with patch.object(client, "_rate_limit", new_callable=AsyncMock):
                client._client = AsyncMock()
                client._client.request = AsyncMock(return_value=mock_response)

                with pytest.raises(RadarrConnectionError, match="redirect.*307"):
                    await client._request("GET", "/api/v3/system/status")

    @pytest.mark.asyncio
    async def test_308_redirect_raises_connection_error(self):
        """Test that a 308 Permanent Redirect raises RadarrConnectionError."""
        client = RadarrClient(
            url="https://radarr.example.com",
            api_key="a" * 32,
        )

        mock_response = MagicMock()
        mock_response.status_code = 308
        mock_response.headers = {"Location": "https://new.example.com/radarr/"}

        with patch.object(client, "_ensure_client", new_callable=AsyncMock):
            with patch.object(client, "_rate_limit", new_callable=AsyncMock):
                client._client = AsyncMock()
                client._client.request = AsyncMock(return_value=mock_response)

                with pytest.raises(RadarrConnectionError, match="redirect.*308"):
                    await client._request("GET", "/api/v3/system/status")

    @pytest.mark.asyncio
    async def test_redirect_missing_location_header(self):
        """Test redirect handling when Location header is absent."""
        client = RadarrClient(
            url="https://radarr.example.com",
            api_key="a" * 32,
        )

        mock_response = MagicMock()
        mock_response.status_code = 301
        mock_response.headers = {}

        with patch.object(client, "_ensure_client", new_callable=AsyncMock):
            with patch.object(client, "_rate_limit", new_callable=AsyncMock):
                client._client = AsyncMock()
                client._client.request = AsyncMock(return_value=mock_response)

                with pytest.raises(RadarrConnectionError, match="unknown"):
                    await client._request("GET", "/api/v3/system/status")

    @pytest.mark.asyncio
    async def test_redirect_does_not_leak_api_key(self):
        """Test that API key is NOT sent to redirect destination.

        Since follow_redirects=False, the client never makes a second request.
        We verify only one request was made (the original), and it raised an error.
        """
        client = RadarrClient(
            url="https://radarr.example.com",
            api_key="a" * 32,
        )

        mock_response = MagicMock()
        mock_response.status_code = 302
        mock_response.headers = {"Location": "https://attacker.example.com/steal-key"}

        with patch.object(client, "_ensure_client", new_callable=AsyncMock):
            with patch.object(client, "_rate_limit", new_callable=AsyncMock):
                mock_request = AsyncMock(return_value=mock_response)
                client._client = AsyncMock()
                client._client.request = mock_request

                with pytest.raises(RadarrConnectionError):
                    await client._request("GET", "/api/v3/system/status")

                # Verify only ONE request was made (no follow-up to redirect target)
                assert mock_request.call_count == 1
