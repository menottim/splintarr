"""
Unit tests for rate_limit_key_func.

Verifies that the rate limiting key function correctly extracts client IPs:
- In production: trusts X-Forwarded-For header (first IP from proxy chain)
- In dev/test: uses request.client.host directly (ignores X-Forwarded-For)
- Handles missing request.client gracefully
"""

from unittest.mock import MagicMock, patch

from splintarr.core.rate_limit import rate_limit_key_func


def _make_request(
    client_host: str | None = "127.0.0.1",
    forwarded_for: str | None = None,
) -> MagicMock:
    """Create a mock Request with optional client and X-Forwarded-For header."""
    request = MagicMock()

    if client_host is not None:
        request.client = MagicMock()
        request.client.host = client_host
    else:
        request.client = None

    headers = {}
    if forwarded_for is not None:
        headers["X-Forwarded-For"] = forwarded_for
    request.headers = headers

    return request


class TestRateLimitKeyFuncProduction:
    """Tests for production environment (behind a reverse proxy)."""

    @patch("splintarr.core.rate_limit.settings")
    def test_uses_x_forwarded_for_in_production(self, mock_settings: MagicMock) -> None:
        """In production, X-Forwarded-For header should be trusted."""
        mock_settings.environment = "production"
        request = _make_request(client_host="10.0.0.1", forwarded_for="203.0.113.50")

        result = rate_limit_key_func(request)

        assert result == "203.0.113.50"

    @patch("splintarr.core.rate_limit.settings")
    def test_uses_first_ip_from_forwarded_chain(self, mock_settings: MagicMock) -> None:
        """When multiple IPs in X-Forwarded-For, use the first (client) IP."""
        mock_settings.environment = "production"
        request = _make_request(
            client_host="10.0.0.1",
            forwarded_for="203.0.113.50, 198.51.100.1, 10.0.0.1",
        )

        result = rate_limit_key_func(request)

        assert result == "203.0.113.50"

    @patch("splintarr.core.rate_limit.settings")
    def test_strips_whitespace_from_forwarded_ip(self, mock_settings: MagicMock) -> None:
        """Whitespace around IPs in X-Forwarded-For should be stripped."""
        mock_settings.environment = "production"
        request = _make_request(
            client_host="10.0.0.1",
            forwarded_for="  203.0.113.50 , 198.51.100.1",
        )

        result = rate_limit_key_func(request)

        assert result == "203.0.113.50"

    @patch("splintarr.core.rate_limit.settings")
    def test_falls_back_to_client_host_when_no_header(
        self, mock_settings: MagicMock
    ) -> None:
        """In production, if X-Forwarded-For is missing, fall back to client.host."""
        mock_settings.environment = "production"
        request = _make_request(client_host="10.0.0.1", forwarded_for=None)

        result = rate_limit_key_func(request)

        assert result == "10.0.0.1"

    @patch("splintarr.core.rate_limit.settings")
    def test_returns_unknown_when_client_is_none_in_production(
        self, mock_settings: MagicMock
    ) -> None:
        """If request.client is None and no X-Forwarded-For, return 'unknown'."""
        mock_settings.environment = "production"
        request = _make_request(client_host=None, forwarded_for=None)

        result = rate_limit_key_func(request)

        assert result == "unknown"


class TestRateLimitKeyFuncDevelopment:
    """Tests for development/test environments (no reverse proxy)."""

    @patch("splintarr.core.rate_limit.settings")
    def test_ignores_x_forwarded_for_in_development(
        self, mock_settings: MagicMock
    ) -> None:
        """In development, X-Forwarded-For must be ignored to prevent spoofing."""
        mock_settings.environment = "development"
        request = _make_request(
            client_host="127.0.0.1",
            forwarded_for="203.0.113.50",
        )

        result = rate_limit_key_func(request)

        assert result == "127.0.0.1"

    @patch("splintarr.core.rate_limit.settings")
    def test_ignores_x_forwarded_for_in_test(self, mock_settings: MagicMock) -> None:
        """In test, X-Forwarded-For must be ignored to prevent spoofing."""
        mock_settings.environment = "test"
        request = _make_request(
            client_host="127.0.0.1",
            forwarded_for="203.0.113.50",
        )

        result = rate_limit_key_func(request)

        assert result == "127.0.0.1"

    @patch("splintarr.core.rate_limit.settings")
    def test_uses_client_host_in_development(self, mock_settings: MagicMock) -> None:
        """In development, always use request.client.host."""
        mock_settings.environment = "development"
        request = _make_request(client_host="192.168.1.100")

        result = rate_limit_key_func(request)

        assert result == "192.168.1.100"

    @patch("splintarr.core.rate_limit.settings")
    def test_returns_unknown_when_client_is_none(
        self, mock_settings: MagicMock
    ) -> None:
        """If request.client is None, return 'unknown'."""
        mock_settings.environment = "development"
        request = _make_request(client_host=None)

        result = rate_limit_key_func(request)

        assert result == "unknown"


class TestGetClientIpConsistency:
    """Verify that auth.get_client_ip returns the correct IP (consistent with rate limiter)."""

    @patch("splintarr.core.rate_limit.settings")
    @patch("splintarr.api.auth.settings")
    def test_get_client_ip_uses_forwarded_for_in_production(
        self, mock_auth_settings: MagicMock, mock_rl_settings: MagicMock
    ) -> None:
        """get_client_ip should return the X-Forwarded-For IP in production."""
        from splintarr.api.auth import get_client_ip

        mock_auth_settings.environment = "production"
        mock_rl_settings.environment = "production"
        request = _make_request(
            client_host="10.0.0.1",
            forwarded_for="203.0.113.50",
        )

        assert get_client_ip(request) == "203.0.113.50"

    @patch("splintarr.core.rate_limit.settings")
    @patch("splintarr.api.auth.settings")
    def test_get_client_ip_ignores_forwarded_for_in_dev(
        self, mock_auth_settings: MagicMock, mock_rl_settings: MagicMock
    ) -> None:
        """get_client_ip should ignore X-Forwarded-For in development."""
        from splintarr.api.auth import get_client_ip

        mock_auth_settings.environment = "development"
        mock_rl_settings.environment = "development"
        request = _make_request(
            client_host="127.0.0.1",
            forwarded_for="203.0.113.50",
        )

        assert get_client_ip(request) == "127.0.0.1"
