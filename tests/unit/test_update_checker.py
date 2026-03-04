"""
Unit tests for update checker service.

Tests cover:
- is_update_available() — version comparison logic
- get_update_state() — returns cached state dict
- check_for_updates() — async GitHub API integration (mocked):
  - Success case: populates cache with latest_version, release_url, release_name
  - Network error: returns empty dict, does not crash
  - Skips prerelease tags
  - Skips draft releases
  - Rate limit (HTTP 403): returns empty dict
  - Non-200 response: returns empty dict
  - Timeout: returns empty dict
  - Invalid JSON / unexpected error: clears cache, returns empty dict
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

import splintarr.services.update_checker as _uc_module
from splintarr.services.update_checker import (
    check_for_updates,
    get_update_state,
    is_update_available,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MOCK_REQUEST = httpx.Request("GET", "https://api.github.com/test")


def _make_release_response(
    tag_name: str = "v2.0.0",
    name: str = "Release v2.0.0",
    html_url: str = "https://github.com/menottim/splintarr/releases/tag/v2.0.0",
    draft: bool = False,
    prerelease: bool = False,
    status_code: int = 200,
) -> httpx.Response:
    """Build an httpx.Response that looks like GitHub's /releases/latest."""
    return httpx.Response(
        status_code=status_code,
        json={
            "tag_name": tag_name,
            "name": name,
            "html_url": html_url,
            "draft": draft,
            "prerelease": prerelease,
        },
        request=MOCK_REQUEST,
    )


@pytest.fixture(autouse=True)
def _reset_update_state():
    """Ensure _update_state is empty before and after every test.

    Because check_for_updates() rebinds the module-level _update_state via
    ``global _update_state``, we must reset through the module reference to
    ensure we always target the current dict object.
    """
    _uc_module._update_state = {}
    yield
    _uc_module._update_state = {}


# ---------------------------------------------------------------------------
# is_update_available tests
# ---------------------------------------------------------------------------


class TestIsUpdateAvailable:
    """Version comparison tests."""

    def test_newer_version_available(self):
        assert is_update_available("1.0.0", "1.1.0") is True

    def test_same_version(self):
        assert is_update_available("1.1.0", "1.1.0") is False

    def test_older_latest_version(self):
        assert is_update_available("2.0.0", "1.0.0") is False

    def test_major_bump(self):
        assert is_update_available("1.9.9", "2.0.0") is True

    def test_patch_bump(self):
        assert is_update_available("1.0.0", "1.0.1") is True

    def test_dev_version_current(self):
        """A dev pre-release is considered older than a stable release."""
        assert is_update_available("1.0.0.dev1", "1.0.0") is True

    def test_invalid_version_string(self):
        """Invalid version strings should return False (not raise)."""
        assert is_update_available("1.0.0", "not-a-version") is False

    def test_both_invalid(self):
        assert is_update_available("bad", "worse") is False


# ---------------------------------------------------------------------------
# get_update_state tests
# ---------------------------------------------------------------------------


class TestGetUpdateState:
    """State cache access tests."""

    def test_returns_empty_when_no_check_done(self):
        result = get_update_state()
        assert result == {}

    def test_returns_copy_not_reference(self):
        """Callers should not be able to mutate the internal cache."""
        _uc_module._update_state["latest_version"] = "1.2.3"
        state = get_update_state()
        state["injected"] = True
        assert "injected" not in _uc_module._update_state


# ---------------------------------------------------------------------------
# check_for_updates tests
# ---------------------------------------------------------------------------


def _patch_httpx_client(mock_response=None, side_effect=None):
    """Return a context-manager that patches httpx.AsyncClient for the service.

    Provides a properly configured AsyncMock that supports `async with`.
    """
    p = patch("splintarr.services.update_checker.httpx.AsyncClient")

    def setup(mock_client_cls):
        instance = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=instance)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        if side_effect is not None:
            instance.get = AsyncMock(side_effect=side_effect)
        else:
            instance.get = AsyncMock(return_value=mock_response)
        return instance

    return p, setup


class TestCheckForUpdates:
    """Async GitHub API integration tests (all network calls mocked)."""

    @pytest.mark.asyncio
    async def test_success_populates_cache(self):
        response = _make_release_response(
            tag_name="v2.0.0",
            name="Release v2.0.0",
            html_url="https://github.com/menottim/splintarr/releases/tag/v2.0.0",
        )
        p, setup = _patch_httpx_client(mock_response=response)
        with p as mock_cls:
            setup(mock_cls)
            result = await check_for_updates()

        assert result["latest_version"] == "2.0.0"
        assert result["release_url"] == "https://github.com/menottim/splintarr/releases/tag/v2.0.0"
        assert result["release_name"] == "Release v2.0.0"
        assert "checked_at" in result

        # Cache should also be populated
        cached = get_update_state()
        assert cached["latest_version"] == "2.0.0"

    @pytest.mark.asyncio
    async def test_strips_v_prefix_from_tag(self):
        response = _make_release_response(tag_name="v1.5.3")
        p, setup = _patch_httpx_client(mock_response=response)
        with p as mock_cls:
            setup(mock_cls)
            result = await check_for_updates()

        assert result["latest_version"] == "1.5.3"

    @pytest.mark.asyncio
    async def test_network_error_returns_empty(self):
        p, setup = _patch_httpx_client(side_effect=httpx.ConnectError("Connection refused"))
        with p as mock_cls:
            setup(mock_cls)
            result = await check_for_updates()

        assert result == {}
        assert get_update_state() == {}

    @pytest.mark.asyncio
    async def test_timeout_returns_empty(self):
        p, setup = _patch_httpx_client(side_effect=httpx.TimeoutException("timed out"))
        with p as mock_cls:
            setup(mock_cls)
            result = await check_for_updates()

        assert result == {}

    @pytest.mark.asyncio
    async def test_skips_prerelease(self):
        response = _make_release_response(prerelease=True)
        p, setup = _patch_httpx_client(mock_response=response)
        with p as mock_cls:
            setup(mock_cls)
            result = await check_for_updates()

        assert result == {}
        assert get_update_state() == {}

    @pytest.mark.asyncio
    async def test_skips_draft(self):
        response = _make_release_response(draft=True)
        p, setup = _patch_httpx_client(mock_response=response)
        with p as mock_cls:
            setup(mock_cls)
            result = await check_for_updates()

        assert result == {}

    @pytest.mark.asyncio
    async def test_rate_limit_403_returns_empty(self):
        response = httpx.Response(
            status_code=403,
            json={"message": "API rate limit exceeded"},
            request=MOCK_REQUEST,
        )
        p, setup = _patch_httpx_client(mock_response=response)
        with p as mock_cls:
            setup(mock_cls)
            result = await check_for_updates()

        assert result == {}

    @pytest.mark.asyncio
    async def test_non_200_returns_empty(self):
        response = httpx.Response(
            status_code=500,
            json={"message": "Internal Server Error"},
            request=MOCK_REQUEST,
        )
        p, setup = _patch_httpx_client(mock_response=response)
        with p as mock_cls:
            setup(mock_cls)
            result = await check_for_updates()

        assert result == {}

    @pytest.mark.asyncio
    async def test_unexpected_error_clears_cache(self):
        """If an unexpected exception occurs, cache should be cleared."""
        # Pre-populate cache via module reference
        _uc_module._update_state["latest_version"] = "1.0.0"
        _uc_module._update_state["checked_at"] = "2026-01-01T00:00:00+00:00"

        p, setup = _patch_httpx_client(side_effect=RuntimeError("unexpected"))
        with p as mock_cls:
            setup(mock_cls)
            result = await check_for_updates()

        assert result == {}
        assert get_update_state() == {}

    @pytest.mark.asyncio
    async def test_sends_correct_headers(self):
        response = _make_release_response()
        p, setup = _patch_httpx_client(mock_response=response)
        with p as mock_cls:
            mock_instance = setup(mock_cls)
            await check_for_updates()

        # Verify the GET call was made with correct headers
        call_kwargs = mock_instance.get.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert headers["Accept"] == "application/vnd.github.v3+json"
        assert "Splintarr/" in headers["User-Agent"]
