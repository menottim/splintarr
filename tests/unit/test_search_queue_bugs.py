"""
Unit tests for search queue bug fixes.

Tests for:
- Bug 1: Pagination off-by-one that skipped the last page
- Bug 2: Radarr "recent" strategy sorting by title instead of recency
- Bug 3: rate_limit_per_second column storing floats in Integer column
- Bug 4: Unbounded cooldown dict memory leak
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from splintarr.models import Instance
from splintarr.services.search_queue import SearchQueueManager


@pytest.fixture
def mock_session_factory():
    """Mock session factory."""
    session = MagicMock()
    return lambda: session


@pytest.fixture
def queue_manager(mock_session_factory):
    """Create queue manager instance."""
    return SearchQueueManager(mock_session_factory)


@pytest.fixture
def mock_instance_sonarr():
    """Create a mock Sonarr instance."""
    instance = MagicMock(spec=Instance)
    instance.id = 1
    instance.instance_type = "sonarr"
    instance.url = "https://sonarr.example.com"
    instance.api_key = "encrypted_key"
    instance.verify_ssl = True
    instance.rate_limit_per_second = 5
    return instance


@pytest.fixture
def mock_instance_radarr():
    """Create a mock Radarr instance."""
    instance = MagicMock(spec=Instance)
    instance.id = 2
    instance.instance_type = "radarr"
    instance.url = "https://radarr.example.com"
    instance.api_key = "encrypted_key"
    instance.verify_ssl = True
    instance.rate_limit_per_second = 5
    return instance


@pytest.fixture
def mock_queue():
    """Create a mock search queue."""
    queue = MagicMock()
    queue.id = 1
    queue.instance_id = 1
    queue.name = "Test Queue"
    queue.strategy = "missing"
    queue.is_active = True
    queue.filters = None
    return queue


class TestPaginationOffByOne:
    """Test that the pagination off-by-one bug is fixed (Bug 1).

    Previously, the code had `if page >= totalRecords / 50: break` which
    would skip the last page. For example, with 100 records and page_size 50,
    page 2 (the last page) would be skipped because 2 >= 100/50.

    The fix removes the redundant page comparison entirely, relying on the
    `if not records: break` guard.
    """

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.decrypt_api_key")
    @patch("splintarr.services.search_queue.SonarrClient")
    async def test_missing_strategy_sonarr_processes_all_pages(
        self,
        mock_sonarr_client,
        mock_decrypt,
        queue_manager,
        mock_queue,
        mock_instance_sonarr,
    ):
        """Test that missing strategy processes all pages for Sonarr.

        Simulates 100 total records across 2 pages of 50. Before the fix,
        page 2 was skipped due to the off-by-one.
        """
        mock_decrypt.return_value = "test_api_key"
        # Bypass rate limiter so all items are processed
        queue_manager._check_rate_limit = AsyncMock(return_value=True)

        # Build mock client that returns 2 pages then empty
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        page1_records = [{"id": i} for i in range(1, 51)]
        page2_records = [{"id": i} for i in range(51, 101)]

        mock_client.get_wanted_missing.side_effect = [
            {"records": page1_records, "totalRecords": 100},
            {"records": page2_records, "totalRecords": 100},
            {"records": [], "totalRecords": 100},
        ]
        mock_client.search_episodes.return_value = {"id": 123}
        mock_sonarr_client.return_value = mock_client

        db = MagicMock()
        result = await queue_manager._execute_missing_strategy(
            mock_queue, mock_instance_sonarr, db
        )

        # All 100 items should be searched (both pages processed)
        assert result["items_searched"] == 100
        assert result["items_found"] == 100

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.decrypt_api_key")
    @patch("splintarr.services.search_queue.RadarrClient")
    async def test_missing_strategy_radarr_processes_all_pages(
        self,
        mock_radarr_client,
        mock_decrypt,
        queue_manager,
        mock_queue,
        mock_instance_radarr,
    ):
        """Test that missing strategy processes all pages for Radarr."""
        mock_decrypt.return_value = "test_api_key"
        queue_manager._check_rate_limit = AsyncMock(return_value=True)

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        page1_records = [{"id": i} for i in range(1, 51)]
        page2_records = [{"id": i} for i in range(51, 101)]

        mock_client.get_wanted_missing.side_effect = [
            {"records": page1_records, "totalRecords": 100},
            {"records": page2_records, "totalRecords": 100},
            {"records": [], "totalRecords": 100},
        ]
        mock_client.search_movies.return_value = {"id": 123}
        mock_radarr_client.return_value = mock_client

        db = MagicMock()
        result = await queue_manager._execute_missing_strategy(
            mock_queue, mock_instance_radarr, db
        )

        assert result["items_searched"] == 100
        assert result["items_found"] == 100

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.decrypt_api_key")
    @patch("splintarr.services.search_queue.SonarrClient")
    async def test_cutoff_strategy_sonarr_processes_all_pages(
        self,
        mock_sonarr_client,
        mock_decrypt,
        queue_manager,
        mock_queue,
        mock_instance_sonarr,
    ):
        """Test that cutoff strategy processes all pages for Sonarr."""
        mock_decrypt.return_value = "test_api_key"
        queue_manager._check_rate_limit = AsyncMock(return_value=True)
        mock_queue.strategy = "cutoff_unmet"

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        page1_records = [{"id": i} for i in range(1, 51)]
        page2_records = [{"id": i} for i in range(51, 101)]

        mock_client.get_wanted_cutoff.side_effect = [
            {"records": page1_records, "totalRecords": 100},
            {"records": page2_records, "totalRecords": 100},
            {"records": [], "totalRecords": 100},
        ]
        mock_client.search_episodes.return_value = {"id": 123}
        mock_sonarr_client.return_value = mock_client

        db = MagicMock()
        result = await queue_manager._execute_cutoff_strategy(
            mock_queue, mock_instance_sonarr, db
        )

        assert result["items_searched"] == 100
        assert result["items_found"] == 100

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.decrypt_api_key")
    @patch("splintarr.services.search_queue.RadarrClient")
    async def test_cutoff_strategy_radarr_processes_all_pages(
        self,
        mock_radarr_client,
        mock_decrypt,
        queue_manager,
        mock_queue,
        mock_instance_radarr,
    ):
        """Test that cutoff strategy processes all pages for Radarr."""
        mock_decrypt.return_value = "test_api_key"
        queue_manager._check_rate_limit = AsyncMock(return_value=True)
        mock_queue.strategy = "cutoff_unmet"

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        page1_records = [{"id": i} for i in range(1, 51)]
        page2_records = [{"id": i} for i in range(51, 101)]

        mock_client.get_wanted_cutoff.side_effect = [
            {"records": page1_records, "totalRecords": 100},
            {"records": page2_records, "totalRecords": 100},
            {"records": [], "totalRecords": 100},
        ]
        mock_client.search_movies.return_value = {"id": 123}
        mock_radarr_client.return_value = mock_client

        db = MagicMock()
        result = await queue_manager._execute_cutoff_strategy(
            mock_queue, mock_instance_radarr, db
        )

        assert result["items_searched"] == 100
        assert result["items_found"] == 100

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.decrypt_api_key")
    @patch("splintarr.services.search_queue.SonarrClient")
    async def test_pagination_stops_on_empty_records(
        self,
        mock_sonarr_client,
        mock_decrypt,
        queue_manager,
        mock_queue,
        mock_instance_sonarr,
    ):
        """Test that pagination terminates when empty records are returned."""
        mock_decrypt.return_value = "test_api_key"
        queue_manager._check_rate_limit = AsyncMock(return_value=True)

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        # Single page of 10 records, then empty
        mock_client.get_wanted_missing.side_effect = [
            {"records": [{"id": i} for i in range(1, 11)], "totalRecords": 10},
            {"records": [], "totalRecords": 10},
        ]
        mock_client.search_episodes.return_value = {"id": 123}
        mock_sonarr_client.return_value = mock_client

        db = MagicMock()
        result = await queue_manager._execute_missing_strategy(
            mock_queue, mock_instance_sonarr, db
        )

        assert result["items_searched"] == 10
        # Should have called get_wanted_missing exactly twice (page 1 + empty page 2)
        assert mock_client.get_wanted_missing.call_count == 2


class TestRadarrRecentStrategySortOrder:
    """Test that Radarr recent strategy sorts by recency, not title (Bug 2).

    Previously, the Radarr branch used sort_key="title", sort_dir="ascending"
    which is alphabetical. The fix changes it to sort_key="added",
    sort_dir="descending" for proper recency sorting.
    """

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.decrypt_api_key")
    @patch("splintarr.services.search_queue.RadarrClient")
    async def test_radarr_recent_strategy_uses_added_sort(
        self,
        mock_radarr_client,
        mock_decrypt,
        queue_manager,
        mock_queue,
        mock_instance_radarr,
    ):
        """Test that Radarr recent strategy sorts by 'added' descending."""
        mock_decrypt.return_value = "test_api_key"
        mock_queue.strategy = "recent"

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get_wanted_missing.return_value = {
            "records": [{"id": 1}],
            "totalRecords": 1,
        }
        mock_client.search_movies.return_value = {"id": 123}
        mock_radarr_client.return_value = mock_client

        db = MagicMock()
        await queue_manager._execute_recent_strategy(
            mock_queue, mock_instance_radarr, db
        )

        # Verify the call used correct sort parameters
        mock_client.get_wanted_missing.assert_called_once_with(
            page=1,
            page_size=50,
            sort_key="added",
            sort_dir="descending",
        )

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.decrypt_api_key")
    @patch("splintarr.services.search_queue.SonarrClient")
    async def test_sonarr_recent_strategy_uses_airdateutc_sort(
        self,
        mock_sonarr_client,
        mock_decrypt,
        queue_manager,
        mock_queue,
        mock_instance_sonarr,
    ):
        """Test that Sonarr recent strategy still uses airDateUtc descending."""
        mock_decrypt.return_value = "test_api_key"
        mock_queue.strategy = "recent"

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get_wanted_missing.return_value = {
            "records": [{"id": 1}],
            "totalRecords": 1,
        }
        mock_client.search_episodes.return_value = {"id": 123}
        mock_sonarr_client.return_value = mock_client

        db = MagicMock()
        await queue_manager._execute_recent_strategy(
            mock_queue, mock_instance_sonarr, db
        )

        # Verify the call used correct sort parameters
        mock_client.get_wanted_missing.assert_called_once_with(
            page=1,
            page_size=50,
            sort_key="airDateUtc",
            sort_dir="descending",
        )


class TestRateLimitColumnType:
    """Test that rate_limit_per_second stores float values correctly (Bug 3).

    Previously, the column was Integer which truncated values < 1.0 to 0,
    breaking rate limiting for instances with low request rates.
    """

    def test_rate_limit_stores_float_value(self, db_session):
        """Test that fractional rate limits are stored correctly."""
        from splintarr.models.user import User

        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Slow Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
            rate_limit_per_second=0.5,
        )
        db_session.add(instance)
        db_session.commit()

        # Refresh from DB to verify storage
        db_session.refresh(instance)
        assert instance.rate_limit_per_second == 0.5

    def test_rate_limit_stores_sub_one_value(self, db_session):
        """Test that sub-1.0 rate limits (e.g., from rate_limit_per_minute / 60) are preserved."""
        from splintarr.models.user import User

        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        # Simulate: rate_limit_per_minute = 30 -> per_second = 30/60 = 0.5
        rate_per_second = 30.0 / 60.0

        instance = Instance(
            user_id=user.id,
            name="Rate Limited Instance",
            instance_type="radarr",
            url="https://radarr.example.com",
            api_key="key",
            rate_limit_per_second=rate_per_second,
        )
        db_session.add(instance)
        db_session.commit()

        db_session.refresh(instance)
        assert instance.rate_limit_per_second == pytest.approx(0.5)
        assert instance.rate_limit_per_second > 0  # Must not truncate to 0

    def test_rate_limit_default_is_float(self, db_session):
        """Test that the default rate limit is a float value."""
        from splintarr.models.user import User

        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Default Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        db_session.refresh(instance)
        assert instance.rate_limit_per_second == pytest.approx(5.0)

    def test_rate_limit_very_small_float(self, db_session):
        """Test that very small float values (e.g., 1 req per 10 min) are stored."""
        from splintarr.models.user import User

        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        # 1 request per 10 minutes = 1/600 ~= 0.00167
        rate_per_second = 1.0 / 600.0

        instance = Instance(
            user_id=user.id,
            name="Very Slow Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
            rate_limit_per_second=rate_per_second,
        )
        db_session.add(instance)
        db_session.commit()

        db_session.refresh(instance)
        assert instance.rate_limit_per_second == pytest.approx(rate_per_second)
        assert instance.rate_limit_per_second > 0


class TestCooldownMemoryLeak:
    """Test that expired cooldown entries are cleaned up (Bug 4).

    Previously, _search_cooldowns grew without bound because expired entries
    were never removed. The fix deletes expired entries inside _is_in_cooldown().
    """

    def test_expired_cooldown_is_removed_from_dict(self, queue_manager):
        """Test that checking an expired cooldown removes the entry."""
        item_key = "test_expired_item"

        # Set a cooldown in the past
        past_time = datetime.utcnow() - timedelta(hours=25)
        queue_manager._search_cooldowns[item_key] = past_time

        # Verify the entry exists
        assert item_key in queue_manager._search_cooldowns

        # Check cooldown (should return False and clean up)
        result = queue_manager._is_in_cooldown(item_key, cooldown_hours=24)

        assert result is False
        assert item_key not in queue_manager._search_cooldowns

    def test_active_cooldown_is_not_removed(self, queue_manager):
        """Test that an active (non-expired) cooldown entry is kept."""
        item_key = "test_active_item"

        # Set a recent cooldown
        queue_manager._set_cooldown(item_key)

        # Check cooldown (should return True and keep the entry)
        result = queue_manager._is_in_cooldown(item_key, cooldown_hours=24)

        assert result is True
        assert item_key in queue_manager._search_cooldowns

    def test_multiple_expired_entries_cleaned_on_check(self, queue_manager):
        """Test that expired entries are cleaned up when individually checked."""
        past_time = datetime.utcnow() - timedelta(hours=25)

        # Add many expired entries
        for i in range(100):
            queue_manager._search_cooldowns[f"expired_{i}"] = past_time

        # Also add an active entry
        queue_manager._set_cooldown("active_item")

        assert len(queue_manager._search_cooldowns) == 101

        # Check each expired item individually
        for i in range(100):
            result = queue_manager._is_in_cooldown(f"expired_{i}", cooldown_hours=24)
            assert result is False

        # Expired entries should be cleaned up
        assert len(queue_manager._search_cooldowns) == 1
        assert "active_item" in queue_manager._search_cooldowns

    def test_cooldown_entry_removed_exactly_at_expiry(self, queue_manager):
        """Test that an entry exactly at the expiry boundary is removed."""
        item_key = "test_boundary_item"

        # Set a cooldown exactly 24 hours ago
        exactly_expired = datetime.utcnow() - timedelta(hours=24)
        queue_manager._search_cooldowns[item_key] = exactly_expired

        # At exactly the boundary (now >= cooldown_end), should be expired and removed
        result = queue_manager._is_in_cooldown(item_key, cooldown_hours=24)

        assert result is False
        assert item_key not in queue_manager._search_cooldowns

    def test_new_item_not_in_cooldown_no_side_effects(self, queue_manager):
        """Test that checking a non-existent item has no side effects."""
        assert len(queue_manager._search_cooldowns) == 0

        result = queue_manager._is_in_cooldown("nonexistent_item")

        assert result is False
        assert len(queue_manager._search_cooldowns) == 0
