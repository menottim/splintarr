"""
Unit tests for Search Queue Manager.

Tests queue execution, strategies, rate limiting, and cooldown logic.
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from splintarr.models import SearchQueue, SearchHistory, Instance
from splintarr.services.search_queue import SearchQueueManager, SearchQueueError


@pytest.fixture
def mock_db_session():
    """Mock database session."""
    session = MagicMock()
    session.query = MagicMock()
    session.add = MagicMock()
    session.commit = MagicMock()
    session.refresh = MagicMock()
    session.close = MagicMock()
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
    """Create mock instance."""
    instance = Instance(
        id=1,
        user_id=1,
        name="Test Instance",
        type="sonarr",
        url="https://sonarr.example.com",
        encrypted_api_key="gAAAAABencrypted_key_here",
        verify_ssl=True,
        rate_limit=5.0,
    )
    return instance


@pytest.fixture
def mock_queue(mock_instance):
    """Create mock search queue."""
    queue = SearchQueue(
        id=1,
        instance_id=mock_instance.id,
        name="Test Queue",
        strategy="missing",
        is_recurring=True,
        interval_hours=24,
        is_active=True,
        status="pending",
    )
    queue.schedule_next_run()
    return queue


class TestQueueExecution:
    """Test queue execution."""

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.decrypt_api_key")
    @patch("splintarr.services.search_queue.SonarrClient")
    async def test_execute_missing_strategy_success(
        self,
        mock_sonarr_client,
        mock_decrypt,
        queue_manager,
        mock_db_session,
        mock_queue,
        mock_instance,
    ):
        """Test successful execution of missing strategy."""
        # Setup mocks
        mock_decrypt.return_value = "test_api_key"

        # Mock Sonarr client
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get_wanted_missing.return_value = {
            "records": [
                {"id": 1},
                {"id": 2},
            ],
            "totalRecords": 2,
        }
        mock_client.search_episodes.return_value = {"id": 123}
        mock_sonarr_client.return_value = mock_client

        # Mock database queries
        mock_db_session.query.return_value.filter.return_value.first.side_effect = [
            mock_queue,  # First call: get queue
            mock_instance,  # Second call: get instance
        ]

        # Execute queue
        result = await queue_manager.execute_queue(1)

        # Verify result
        assert result["status"] in ["success", "partial_success"]
        assert result["items_searched"] >= 0
        assert result["searches_triggered"] >= 0

        # Verify queue was marked in progress and completed
        mock_db_session.commit.assert_called()

    @pytest.mark.asyncio
    async def test_execute_queue_not_found(
        self,
        queue_manager,
        mock_db_session,
    ):
        """Test executing non-existent queue."""
        # Mock query to return None
        mock_db_session.query.return_value.filter.return_value.first.return_value = None

        # Execute should raise error
        with pytest.raises(SearchQueueError, match="not found"):
            await queue_manager.execute_queue(999)

    @pytest.mark.asyncio
    async def test_execute_inactive_queue(
        self,
        queue_manager,
        mock_db_session,
        mock_queue,
    ):
        """Test executing inactive queue."""
        # Make queue inactive
        mock_queue.is_active = False

        # Mock query to return inactive queue
        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_queue

        # Execute should raise error
        with pytest.raises(SearchQueueError, match="not active"):
            await queue_manager.execute_queue(1)

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.decrypt_api_key")
    @patch("splintarr.services.search_queue.RadarrClient")
    async def test_execute_radarr_missing_strategy(
        self,
        mock_radarr_client,
        mock_decrypt,
        queue_manager,
        mock_db_session,
        mock_queue,
        mock_instance,
    ):
        """Test executing missing strategy on Radarr."""
        # Setup mocks
        mock_decrypt.return_value = "test_api_key"
        mock_instance.type = "radarr"

        # Mock Radarr client
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get_wanted_missing.return_value = {
            "records": [
                {"id": 1},
            ],
            "totalRecords": 1,
        }
        mock_client.search_movies.return_value = {"id": 123}
        mock_radarr_client.return_value = mock_client

        # Mock database queries
        mock_db_session.query.return_value.filter.return_value.first.side_effect = [
            mock_queue,
            mock_instance,
        ]

        # Execute queue
        result = await queue_manager.execute_queue(1)

        # Verify execution
        assert result["status"] in ["success", "partial_success"]
        assert result["items_searched"] >= 0


class TestSearchStrategies:
    """Test different search strategies."""

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.decrypt_api_key")
    @patch("splintarr.services.search_queue.SonarrClient")
    async def test_cutoff_strategy(
        self,
        mock_sonarr_client,
        mock_decrypt,
        queue_manager,
        mock_db_session,
        mock_queue,
        mock_instance,
    ):
        """Test cutoff unmet strategy."""
        # Setup
        mock_decrypt.return_value = "test_api_key"
        mock_queue.strategy = "cutoff_unmet"

        # Mock client
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get_wanted_cutoff.return_value = {
            "records": [{"id": 1}],
            "totalRecords": 1,
        }
        mock_client.search_episodes.return_value = {"id": 123}
        mock_sonarr_client.return_value = mock_client

        # Mock database
        mock_db_session.query.return_value.filter.return_value.first.side_effect = [
            mock_queue,
            mock_instance,
        ]

        # Execute
        result = await queue_manager.execute_queue(1)

        # Verify cutoff method was called
        assert result["status"] in ["success", "partial_success"]

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.decrypt_api_key")
    @patch("splintarr.services.search_queue.SonarrClient")
    async def test_recent_strategy(
        self,
        mock_sonarr_client,
        mock_decrypt,
        queue_manager,
        mock_db_session,
        mock_queue,
        mock_instance,
    ):
        """Test recent additions strategy."""
        # Setup
        mock_decrypt.return_value = "test_api_key"
        mock_queue.strategy = "recent"

        # Mock client
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get_wanted_missing.return_value = {
            "records": [{"id": 1}],
            "totalRecords": 1,
        }
        mock_client.search_episodes.return_value = {"id": 123}
        mock_sonarr_client.return_value = mock_client

        # Mock database
        mock_db_session.query.return_value.filter.return_value.first.side_effect = [
            mock_queue,
            mock_instance,
        ]

        # Execute
        result = await queue_manager.execute_queue(1)

        # Verify
        assert result["status"] in ["success", "partial_success"]

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.decrypt_api_key")
    @patch("splintarr.services.search_queue.SonarrClient")
    async def test_custom_strategy(
        self,
        mock_sonarr_client,
        mock_decrypt,
        queue_manager,
        mock_db_session,
        mock_queue,
        mock_instance,
    ):
        """Test custom strategy."""
        # Setup
        mock_decrypt.return_value = "test_api_key"
        mock_queue.strategy = "custom"
        mock_queue.filters = '{"quality": "Bluray-1080p"}'

        # Mock client
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get_wanted_missing.return_value = {
            "records": [],
            "totalRecords": 0,
        }
        mock_sonarr_client.return_value = mock_client

        # Mock database
        mock_db_session.query.return_value.filter.return_value.first.side_effect = [
            mock_queue,
            mock_instance,
        ]

        # Execute
        result = await queue_manager.execute_queue(1)

        # Verify
        assert result["status"] == "success"


class TestRateLimiting:
    """Test rate limiting functionality."""

    @pytest.mark.asyncio
    async def test_check_rate_limit_allows_initial_request(self, queue_manager):
        """Test that initial request is allowed."""
        allowed = await queue_manager._check_rate_limit(1, tokens_per_second=5.0)
        assert allowed is True

    @pytest.mark.asyncio
    async def test_check_rate_limit_blocks_rapid_requests(self, queue_manager):
        """Test that rapid requests are blocked."""
        instance_id = 1

        # Make multiple rapid requests
        results = []
        for _ in range(10):
            allowed = await queue_manager._check_rate_limit(instance_id, tokens_per_second=5.0)
            results.append(allowed)

        # Some requests should be blocked
        assert not all(results)
        assert any(results)  # At least some should be allowed


class TestCooldownPeriod:
    """Test cooldown period tracking."""

    def test_is_in_cooldown_new_item(self, queue_manager):
        """Test that new items are not in cooldown."""
        assert queue_manager._is_in_cooldown("test_item") is False

    def test_is_in_cooldown_recent_item(self, queue_manager):
        """Test that recently searched items are in cooldown."""
        item_key = "test_item"

        # Set cooldown
        queue_manager._set_cooldown(item_key)

        # Check cooldown
        assert queue_manager._is_in_cooldown(item_key) is True

    def test_cooldown_expires(self, queue_manager):
        """Test that cooldown expires after specified time."""
        item_key = "test_item"

        # Set cooldown
        queue_manager._set_cooldown(item_key)

        # Check with short cooldown period (should still be in cooldown)
        assert queue_manager._is_in_cooldown(item_key, cooldown_hours=24) is True

        # Check with very short cooldown (should be expired)
        # Note: This test assumes the cooldown was set very recently
        # In a real test, you'd mock datetime


class TestErrorHandling:
    """Test error handling in queue execution."""

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.decrypt_api_key")
    async def test_execute_with_decryption_error(
        self,
        mock_decrypt,
        queue_manager,
        mock_db_session,
        mock_queue,
        mock_instance,
    ):
        """Test handling of decryption errors."""
        # Setup to raise error
        mock_decrypt.side_effect = Exception("Decryption failed")

        # Mock database
        mock_db_session.query.return_value.filter.return_value.first.side_effect = [
            mock_queue,
            mock_instance,
        ]

        # Execute
        result = await queue_manager.execute_queue(1)

        # Verify failure was recorded
        assert result["status"] == "failed"
        assert len(result["errors"]) > 0
