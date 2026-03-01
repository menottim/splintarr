"""
Unit tests for Prowlarr rate limit integration into search execution.

Tests verify that execute_queue correctly integrates IndexerRateLimitService
to resolve effective rate limits before searching, and that the effective max
items is correctly applied in _search_paginated_records.

Tests:
1. Prowlarr caps max_items below queue max
2. No Prowlarr config -> queue max_items_per_run used unchanged
3. Prowlarr budget=0 -> warning logged and 0 items searched
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from splintarr.models import Instance, SearchQueue
from splintarr.services.search_queue import SearchQueueManager


@pytest.fixture
def mock_db_session():
    """Mock database session with flexible query support.

    The mock returns None for any query().filter().first() call by default.
    Tests set up specific return values via _build_execute_mocks.
    """
    session = MagicMock()
    session.add = MagicMock()
    session.commit = MagicMock()
    session.refresh = MagicMock()
    session.close = MagicMock()
    # Default: query().filter().first() returns None
    session.query.return_value.filter.return_value.first.return_value = None
    # query().filter().all() returns [] (for library item loading)
    session.query.return_value.filter.return_value.all.return_value = []
    return session


@pytest.fixture
def mock_session_factory(mock_db_session):
    """Mock session factory."""
    return lambda: mock_db_session


@pytest.fixture
def queue_manager(mock_session_factory):
    """Create queue manager instance."""
    return SearchQueueManager(mock_session_factory)


@pytest.fixture
def mock_instance():
    """Create a mock Sonarr instance with standard attributes."""
    instance = MagicMock(spec=Instance)
    instance.id = 1
    instance.user_id = 1
    instance.name = "Test Sonarr"
    instance.instance_type = "sonarr"
    instance.url = "http://sonarr:8989"
    instance.api_key = "gAAAAABencrypted_key_here"
    instance.verify_ssl = False
    instance.rate_limit_per_second = 5.0
    instance.is_active = True
    return instance


@pytest.fixture
def mock_queue():
    """Create a mock search queue with max_items_per_run=50."""
    queue = MagicMock(spec=SearchQueue)
    queue.id = 1
    queue.instance_id = 1
    queue.name = "Test Queue"
    queue.strategy = "missing"
    queue.is_active = True
    queue.max_items_per_run = 50
    queue.cooldown_mode = "adaptive"
    queue.cooldown_hours = None
    queue.filters = None
    queue.season_pack_enabled = False
    queue.season_pack_threshold = 3
    queue.mark_in_progress = MagicMock()
    queue.mark_completed = MagicMock()
    queue.mark_failed = MagicMock()
    queue.consecutive_failures = 0
    return queue


def _build_execute_mocks(mock_db_session, mock_queue, mock_instance):
    """Wire up DB session mocks so execute_queue can load queue + instance.

    Uses a callable side_effect that returns queue for the first call,
    instance for the second, and None for all subsequent calls. This avoids
    StopIteration errors when the notification code also queries the DB.
    """
    call_count = {"n": 0}
    results = [mock_queue, mock_instance]

    def _first_side_effect():
        idx = call_count["n"]
        call_count["n"] += 1
        if idx < len(results):
            return results[idx]
        return None

    mock_db_session.query.return_value.filter.return_value.first.side_effect = (
        _first_side_effect
    )


def _build_sonarr_client(records=None):
    """Build a mock SonarrClient async context manager."""
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    if records is None:
        records = []

    mock_client.get_wanted_missing.return_value = {
        "records": records,
        "totalRecords": len(records),
    }
    mock_client.search_episodes.return_value = {"id": 999}
    return mock_client


class TestProwlarrCapsMaxItems:
    """When Prowlarr returns max_items < queue.max_items_per_run, the lower value wins."""

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.decrypt_api_key")
    @patch("splintarr.services.search_queue.SonarrClient")
    async def test_prowlarr_caps_max_items(
        self,
        mock_sonarr_cls,
        mock_decrypt,
        queue_manager,
        mock_db_session,
        mock_queue,
        mock_instance,
    ):
        """Prowlarr returns max_items=10 with queue max=50 -> effective_max=10."""
        mock_decrypt.return_value = "test_api_key"

        # Build 20 records so we can observe truncation
        records = [{"id": i} for i in range(1, 21)]
        mock_client = _build_sonarr_client(records)
        mock_sonarr_cls.return_value = mock_client

        _build_execute_mocks(mock_db_session, mock_queue, mock_instance)

        # Mock IndexerRateLimitService to return max_items=10, source=prowlarr
        mock_rate_service = AsyncMock()
        mock_rate_service.get_effective_limit.return_value = {
            "rate_per_second": 5.0,
            "max_items": 10,
            "source": "prowlarr",
        }

        with patch(
            "splintarr.services.indexer_rate_limit.IndexerRateLimitService",
            return_value=mock_rate_service,
        ):
            result = await queue_manager.execute_queue(1)

        # The queue's max_items_per_run is 50, but Prowlarr capped it to 10.
        # With 20 records and effective_max=10, at most 10 should be searched.
        assert result["status"] in ("success", "partial_success")
        assert result["items_searched"] <= 10

        # Verify the rate service was called with the right arguments
        mock_rate_service.get_effective_limit.assert_awaited_once_with(
            instance_id=mock_instance.id,
            user_id=mock_instance.user_id,
            instance_rate=mock_instance.rate_limit_per_second or 5.0,
            instance_url=mock_instance.url,
        )


class TestProwlarrNoConfigUsesQueueMax:
    """When Prowlarr returns source='instance', queue max_items_per_run is used unchanged."""

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.decrypt_api_key")
    @patch("splintarr.services.search_queue.SonarrClient")
    async def test_prowlarr_no_config_uses_queue_max(
        self,
        mock_sonarr_cls,
        mock_decrypt,
        queue_manager,
        mock_db_session,
        mock_queue,
        mock_instance,
    ):
        """No Prowlarr config -> source='instance', max_items=None, queue max used."""
        mock_decrypt.return_value = "test_api_key"

        # Build 5 records (less than queue max of 50)
        records = [{"id": i} for i in range(1, 6)]
        mock_client = _build_sonarr_client(records)
        mock_sonarr_cls.return_value = mock_client

        _build_execute_mocks(mock_db_session, mock_queue, mock_instance)

        # Mock IndexerRateLimitService returning instance fallback
        mock_rate_service = AsyncMock()
        mock_rate_service.get_effective_limit.return_value = {
            "rate_per_second": 5.0,
            "max_items": None,
            "source": "instance",
        }

        with patch(
            "splintarr.services.indexer_rate_limit.IndexerRateLimitService",
            return_value=mock_rate_service,
        ):
            result = await queue_manager.execute_queue(1)

        # All 5 records should be searched (5 < 50 queue max)
        assert result["status"] in ("success", "partial_success")
        assert result["items_searched"] == 5


class TestProwlarrBudgetZeroLogsWarning:
    """When Prowlarr returns max_items=0, effective_max=0 and a warning is logged."""

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.decrypt_api_key")
    @patch("splintarr.services.search_queue.SonarrClient")
    async def test_prowlarr_budget_zero_logs_warning(
        self,
        mock_sonarr_cls,
        mock_decrypt,
        queue_manager,
        mock_db_session,
        mock_queue,
        mock_instance,
        capsys,
    ):
        """Prowlarr budget=0 -> effective_max=0, WARNING logged, 0 items searched."""
        mock_decrypt.return_value = "test_api_key"

        # Build 10 records
        records = [{"id": i} for i in range(1, 11)]
        mock_client = _build_sonarr_client(records)
        mock_sonarr_cls.return_value = mock_client

        _build_execute_mocks(mock_db_session, mock_queue, mock_instance)

        # Mock IndexerRateLimitService returning max_items=0 (fully exhausted)
        mock_rate_service = AsyncMock()
        mock_rate_service.get_effective_limit.return_value = {
            "rate_per_second": 5.0,
            "max_items": 0,
            "source": "prowlarr",
        }

        with patch(
            "splintarr.services.indexer_rate_limit.IndexerRateLimitService",
            return_value=mock_rate_service,
        ):
            result = await queue_manager.execute_queue(1)

        # With effective_max=0, no items should be searched
        assert result["items_searched"] == 0

        # Verify warning was logged about exhausted Prowlarr budget.
        # structlog writes to stdout, not Python logging, so we use capsys.
        captured = capsys.readouterr()
        assert "search_queue_prowlarr_budget_exhausted" in captured.out, (
            "Expected a WARNING log with event 'search_queue_prowlarr_budget_exhausted' "
            f"but got stdout:\n{captured.out}"
        )
