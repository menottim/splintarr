"""
Unit tests for IndexerRateLimitService.

Tests cover:
1. No ProwlarrConfig for user returns instance rate fallback
2. Prowlarr with configured limits caps max_items to remaining budget
3. Prowlarr unreachable (exception) falls back to instance rate
4. Instance URL doesn't match any Prowlarr application -> fallback
5. Multiple indexers with different budgets -> uses minimum
6. Disabled indexer (disabled_till set) is skipped
7. All indexers have query_limit=None -> fallback
"""

from unittest.mock import AsyncMock, patch

import pytest

from splintarr.core.security import hash_password
from splintarr.models.prowlarr import ProwlarrConfig
from splintarr.models.user import User
from splintarr.services.indexer_rate_limit import IndexerRateLimitService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def user(db_session):
    """Create a test user."""
    u = User(
        username="ratelimituser",
        password_hash=hash_password("TestP@ssw0rd123!"),
        is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def prowlarr_config(db_session, user):
    """Create a ProwlarrConfig for the test user."""
    config = ProwlarrConfig(
        user_id=user.id,
        url="http://prowlarr:9696",
        encrypted_api_key="gAAAAA_fake_encrypted_key",
        verify_ssl=False,
        is_active=True,
    )
    db_session.add(config)
    db_session.commit()
    return config


@pytest.fixture
def service(db_session):
    """Create an IndexerRateLimitService instance."""
    return IndexerRateLimitService(db=db_session)


# ---------------------------------------------------------------------------
# Helpers: build mock Prowlarr responses
# ---------------------------------------------------------------------------


def _make_indexer(
    indexer_id: int,
    name: str,
    tags: list[int],
    query_limit: int | None = None,
    disabled_till: str | None = None,
) -> dict:
    """Build a Prowlarr indexer dict matching ProwlarrClient.get_indexers() output."""
    return {
        "id": indexer_id,
        "name": name,
        "enable": True,
        "protocol": "usenet",
        "query_limit": query_limit,
        "grab_limit": None,
        "limits_unit": "day" if query_limit else None,
        "tags": tags,
        "disabled_till": disabled_till,
    }


def _make_app(
    app_id: int,
    name: str,
    base_url: str,
    tags: list[int],
) -> dict:
    """Build a Prowlarr application dict matching ProwlarrClient.get_applications() output."""
    return {
        "id": app_id,
        "name": name,
        "implementation": "Sonarr",
        "base_url": base_url,
        "tags": tags,
    }


def _make_stats(indexer_id: int, queries: int = 0) -> dict:
    """Build an entry for the stats dict keyed by indexer_id."""
    return {
        "name": f"indexer-{indexer_id}",
        "queries": queries,
        "grabs": 0,
        "failed_queries": 0,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNoProwlarrConfig:
    """When no ProwlarrConfig exists for the user, fallback to instance rate."""

    @pytest.mark.asyncio
    async def test_no_prowlarr_config_returns_instance_rate(
        self, service, user
    ) -> None:
        """No ProwlarrConfig in DB -> fallback with source='instance'."""
        result = await service.get_effective_limit(
            instance_id=1,
            user_id=user.id,
            instance_rate=5.0,
            instance_url="http://sonarr:8989",
        )

        assert result["rate_per_second"] == 5.0
        assert result["max_items"] is None
        assert result["source"] == "instance"


class TestProwlarrWithLimits:
    """When Prowlarr is configured and indexers have query limits."""

    @pytest.mark.asyncio
    async def test_prowlarr_with_limits_caps_items(
        self, service, user, prowlarr_config
    ) -> None:
        """100 limit, 60 used -> max_items=40."""
        mock_client = AsyncMock()
        mock_client.get_indexers = AsyncMock(
            return_value=[
                _make_indexer(1, "NZBgeek", tags=[1], query_limit=100),
            ]
        )
        mock_client.get_applications = AsyncMock(
            return_value=[
                _make_app(10, "Sonarr", "http://sonarr:8989", tags=[1]),
            ]
        )
        mock_client.get_indexer_stats = AsyncMock(
            return_value={1: _make_stats(1, queries=60)},
        )
        mock_client.get_indexer_status = AsyncMock(return_value=[])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "splintarr.services.indexer_rate_limit.decrypt_api_key",
                return_value="a" * 32,
            ),
            patch(
                "splintarr.services.indexer_rate_limit.ProwlarrClient",
                return_value=mock_client,
            ),
        ):
            result = await service.get_effective_limit(
                instance_id=1,
                user_id=user.id,
                instance_rate=5.0,
                instance_url="http://sonarr:8989",
            )

        assert result["rate_per_second"] == 5.0
        assert result["max_items"] == 40
        assert result["source"] == "prowlarr"


class TestProwlarrUnreachable:
    """When Prowlarr raises an exception, fallback gracefully."""

    @pytest.mark.asyncio
    async def test_prowlarr_unreachable_falls_back(
        self, service, user, prowlarr_config
    ) -> None:
        """Exception during Prowlarr API calls -> fallback."""
        mock_client = AsyncMock()
        mock_client.get_indexers = AsyncMock(
            side_effect=ConnectionError("Cannot reach Prowlarr")
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "splintarr.services.indexer_rate_limit.decrypt_api_key",
                return_value="a" * 32,
            ),
            patch(
                "splintarr.services.indexer_rate_limit.ProwlarrClient",
                return_value=mock_client,
            ),
        ):
            result = await service.get_effective_limit(
                instance_id=1,
                user_id=user.id,
                instance_rate=5.0,
                instance_url="http://sonarr:8989",
            )

        assert result["rate_per_second"] == 5.0
        assert result["max_items"] is None
        assert result["source"] == "instance"


class TestNoMatchingApp:
    """When instance URL doesn't match any Prowlarr application."""

    @pytest.mark.asyncio
    async def test_no_matching_app_falls_back(
        self, service, user, prowlarr_config
    ) -> None:
        """Instance URL doesn't match any Prowlarr app -> fallback."""
        mock_client = AsyncMock()
        mock_client.get_indexers = AsyncMock(
            return_value=[
                _make_indexer(1, "NZBgeek", tags=[1], query_limit=100),
            ]
        )
        mock_client.get_applications = AsyncMock(
            return_value=[
                # Only radarr registered, no sonarr
                _make_app(10, "Radarr", "http://radarr:7878", tags=[1]),
            ]
        )
        mock_client.get_indexer_stats = AsyncMock(return_value={})
        mock_client.get_indexer_status = AsyncMock(return_value=[])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "splintarr.services.indexer_rate_limit.decrypt_api_key",
                return_value="a" * 32,
            ),
            patch(
                "splintarr.services.indexer_rate_limit.ProwlarrClient",
                return_value=mock_client,
            ),
        ):
            result = await service.get_effective_limit(
                instance_id=1,
                user_id=user.id,
                instance_rate=5.0,
                instance_url="http://sonarr:8989",
            )

        assert result["rate_per_second"] == 5.0
        assert result["max_items"] is None
        assert result["source"] == "instance"


class TestMultipleIndexersUsesMinimum:
    """With multiple indexers, the minimum remaining budget is used."""

    @pytest.mark.asyncio
    async def test_multiple_indexers_uses_minimum(
        self, service, user, prowlarr_config
    ) -> None:
        """3 indexers with different budgets -> min remaining is chosen."""
        mock_client = AsyncMock()
        mock_client.get_indexers = AsyncMock(
            return_value=[
                _make_indexer(1, "Indexer A", tags=[1], query_limit=100),
                _make_indexer(2, "Indexer B", tags=[1], query_limit=50),
                _make_indexer(3, "Indexer C", tags=[1], query_limit=200),
            ]
        )
        mock_client.get_applications = AsyncMock(
            return_value=[
                _make_app(10, "Sonarr", "http://sonarr:8989", tags=[1]),
            ]
        )
        mock_client.get_indexer_stats = AsyncMock(
            return_value={
                1: _make_stats(1, queries=80),   # remaining = 20
                2: _make_stats(2, queries=40),   # remaining = 10  <-- minimum
                3: _make_stats(3, queries=50),   # remaining = 150
            },
        )
        mock_client.get_indexer_status = AsyncMock(return_value=[])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "splintarr.services.indexer_rate_limit.decrypt_api_key",
                return_value="a" * 32,
            ),
            patch(
                "splintarr.services.indexer_rate_limit.ProwlarrClient",
                return_value=mock_client,
            ),
        ):
            result = await service.get_effective_limit(
                instance_id=1,
                user_id=user.id,
                instance_rate=5.0,
                instance_url="http://sonarr:8989",
            )

        assert result["rate_per_second"] == 5.0
        assert result["max_items"] == 10
        assert result["source"] == "prowlarr"


class TestDisabledIndexerSkipped:
    """Indexers with disabled_till set are excluded from budget calculation."""

    @pytest.mark.asyncio
    async def test_disabled_indexer_skipped(
        self, service, user, prowlarr_config
    ) -> None:
        """Disabled indexer is excluded; only active indexer used."""
        mock_client = AsyncMock()
        mock_client.get_indexers = AsyncMock(
            return_value=[
                _make_indexer(
                    1, "Disabled Indexer", tags=[1],
                    query_limit=10,
                    disabled_till="2026-03-01T12:00:00Z",
                ),
                _make_indexer(2, "Active Indexer", tags=[1], query_limit=100),
            ]
        )
        mock_client.get_applications = AsyncMock(
            return_value=[
                _make_app(10, "Sonarr", "http://sonarr:8989", tags=[1]),
            ]
        )
        mock_client.get_indexer_stats = AsyncMock(
            return_value={
                1: _make_stats(1, queries=9),   # remaining=1 but disabled
                2: _make_stats(2, queries=30),  # remaining=70
            },
        )
        mock_client.get_indexer_status = AsyncMock(
            return_value=[
                {"indexer_id": 1, "disabled_till": "2026-03-01T12:00:00Z"},
            ]
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "splintarr.services.indexer_rate_limit.decrypt_api_key",
                return_value="a" * 32,
            ),
            patch(
                "splintarr.services.indexer_rate_limit.ProwlarrClient",
                return_value=mock_client,
            ),
        ):
            result = await service.get_effective_limit(
                instance_id=1,
                user_id=user.id,
                instance_rate=5.0,
                instance_url="http://sonarr:8989",
            )

        # Should use the active indexer's budget (70), not the disabled one (1)
        assert result["max_items"] == 70
        assert result["source"] == "prowlarr"


class TestNoLimitsConfiguredFallsBack:
    """When all indexers have query_limit=None, fallback to instance rate."""

    @pytest.mark.asyncio
    async def test_no_limits_configured_falls_back(
        self, service, user, prowlarr_config
    ) -> None:
        """All indexers have query_limit=None -> fallback."""
        mock_client = AsyncMock()
        mock_client.get_indexers = AsyncMock(
            return_value=[
                _make_indexer(1, "No Limit A", tags=[1], query_limit=None),
                _make_indexer(2, "No Limit B", tags=[1], query_limit=None),
            ]
        )
        mock_client.get_applications = AsyncMock(
            return_value=[
                _make_app(10, "Sonarr", "http://sonarr:8989", tags=[1]),
            ]
        )
        mock_client.get_indexer_stats = AsyncMock(
            return_value={
                1: _make_stats(1, queries=100),
                2: _make_stats(2, queries=200),
            },
        )
        mock_client.get_indexer_status = AsyncMock(return_value=[])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "splintarr.services.indexer_rate_limit.decrypt_api_key",
                return_value="a" * 32,
            ),
            patch(
                "splintarr.services.indexer_rate_limit.ProwlarrClient",
                return_value=mock_client,
            ),
        ):
            result = await service.get_effective_limit(
                instance_id=1,
                user_id=user.id,
                instance_rate=5.0,
                instance_url="http://sonarr:8989",
            )

        assert result["rate_per_second"] == 5.0
        assert result["max_items"] is None
        assert result["source"] == "instance"
