"""Tests for the custom strategy execution in SearchQueueManager.

Verifies that _execute_custom_strategy:
- Fetches from the correct sources based on filters.sources
- Deduplicates records across multiple sources
- Calls apply_custom_filters with the correct arguments
- Passes filtered records into the standard scoring/search pipeline
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from splintarr.services.search_queue import SearchQueueError, SearchQueueManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(series_id: int, episode_id: int) -> dict:
    """Build a minimal Sonarr wanted-API record."""
    return {
        "id": episode_id,
        "seriesId": series_id,
        "seasonNumber": 1,
        "episodeNumber": episode_id,
        "title": f"Episode {episode_id}",
        "series": {"id": series_id, "title": f"Series {series_id}"},
    }


def _api_page(records: list[dict]) -> dict:
    """Wrap records in a Sonarr-style paginated response."""
    return {"records": records, "totalRecords": len(records)}


class _FakeLibraryItem:
    """Minimal stand-in for LibraryItem."""

    def __init__(
        self,
        id: int = 1,
        external_id: int = 100,
        instance_id: int = 1,
        year: int = 2020,
        status: str = "continuing",
        quality_profile: str = "HD-1080p",
    ):
        self.id = id
        self.external_id = external_id
        self.instance_id = instance_id
        self.year = year
        self.status = status
        self.quality_profile = quality_profile
        self.last_searched_at = None
        self.search_attempts = 0

    def record_search(self) -> None:
        self.search_attempts += 1


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    """Create a mock Sonarr instance."""
    instance = MagicMock()
    instance.id = 1
    instance.user_id = 1
    instance.name = "Test Sonarr"
    instance.instance_type = "sonarr"
    instance.url = "https://sonarr.example.com"
    instance.api_key = "gAAAAABencrypted_key"
    instance.verify_ssl = True
    instance.rate_limit_per_second = 5.0
    return instance


@pytest.fixture
def mock_queue():
    """Create a mock queue with custom strategy."""
    queue = MagicMock()
    queue.id = 1
    queue.instance_id = 1
    queue.name = "Custom Queue"
    queue.strategy = "custom"
    queue.is_active = True
    queue.status = "pending"
    queue.is_recurring = False
    queue.max_items_per_run = 50
    queue.cooldown_mode = "adaptive"
    queue.cooldown_hours = None
    queue.season_pack_enabled = False
    queue.season_pack_threshold = 3
    queue.filters = json.dumps({"sources": ["missing"]})
    return queue


# ---------------------------------------------------------------------------
# Source selection tests
# ---------------------------------------------------------------------------


class TestCustomStrategySourceSelection:
    """Custom strategy fetches from the correct API source(s)."""

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.decrypt_api_key")
    @patch("splintarr.services.search_queue.SonarrClient")
    @patch("splintarr.services.search_queue.ExclusionService")
    async def test_missing_only_calls_get_wanted_missing(
        self,
        mock_exclusion_cls,
        mock_sonarr_cls,
        mock_decrypt,
        queue_manager,
        mock_db_session,
        mock_queue,
        mock_instance,
    ):
        """sources: ['missing'] should only call get_wanted_missing."""
        mock_decrypt.return_value = "test_api_key"
        mock_queue.filters = json.dumps({"sources": ["missing"]})

        # Mock client
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get_wanted_missing.return_value = _api_page([])
        mock_client.get_wanted_cutoff.return_value = _api_page([])
        mock_sonarr_cls.return_value = mock_client

        # Mock exclusion service
        mock_exclusion = MagicMock()
        mock_exclusion.get_active_exclusion_keys.return_value = set()
        mock_exclusion_cls.return_value = mock_exclusion

        # Mock library items query — return empty list for both calls
        mock_db_session.query.return_value.filter.return_value.all.return_value = []

        result = await queue_manager._execute_custom_strategy(
            queue=mock_queue,
            instance=mock_instance,
            db=mock_db_session,
        )

        mock_client.get_wanted_missing.assert_called()
        mock_client.get_wanted_cutoff.assert_not_called()
        assert result["status"] == "success"

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.decrypt_api_key")
    @patch("splintarr.services.search_queue.SonarrClient")
    @patch("splintarr.services.search_queue.ExclusionService")
    async def test_cutoff_only_calls_get_wanted_cutoff(
        self,
        mock_exclusion_cls,
        mock_sonarr_cls,
        mock_decrypt,
        queue_manager,
        mock_db_session,
        mock_queue,
        mock_instance,
    ):
        """sources: ['cutoff_unmet'] should only call get_wanted_cutoff."""
        mock_decrypt.return_value = "test_api_key"
        mock_queue.filters = json.dumps({"sources": ["cutoff_unmet"]})

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get_wanted_missing.return_value = _api_page([])
        mock_client.get_wanted_cutoff.return_value = _api_page([])
        mock_sonarr_cls.return_value = mock_client

        mock_exclusion = MagicMock()
        mock_exclusion.get_active_exclusion_keys.return_value = set()
        mock_exclusion_cls.return_value = mock_exclusion

        mock_db_session.query.return_value.filter.return_value.all.return_value = []

        result = await queue_manager._execute_custom_strategy(
            queue=mock_queue,
            instance=mock_instance,
            db=mock_db_session,
        )

        mock_client.get_wanted_cutoff.assert_called()
        mock_client.get_wanted_missing.assert_not_called()
        assert result["status"] == "success"

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.decrypt_api_key")
    @patch("splintarr.services.search_queue.SonarrClient")
    @patch("splintarr.services.search_queue.ExclusionService")
    async def test_both_sources_calls_both_methods(
        self,
        mock_exclusion_cls,
        mock_sonarr_cls,
        mock_decrypt,
        queue_manager,
        mock_db_session,
        mock_queue,
        mock_instance,
    ):
        """sources: ['missing', 'cutoff_unmet'] should call both fetch methods."""
        mock_decrypt.return_value = "test_api_key"
        mock_queue.filters = json.dumps({"sources": ["missing", "cutoff_unmet"]})

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get_wanted_missing.return_value = _api_page([
            _make_record(1, 10),
        ])
        mock_client.get_wanted_cutoff.return_value = _api_page([
            _make_record(2, 20),
        ])
        mock_client.search_episodes.return_value = {"id": 999}
        mock_sonarr_cls.return_value = mock_client

        mock_exclusion = MagicMock()
        mock_exclusion.get_active_exclusion_keys.return_value = set()
        mock_exclusion_cls.return_value = mock_exclusion

        mock_db_session.query.return_value.filter.return_value.all.return_value = []

        await queue_manager._execute_custom_strategy(
            queue=mock_queue,
            instance=mock_instance,
            db=mock_db_session,
        )

        mock_client.get_wanted_missing.assert_called()
        mock_client.get_wanted_cutoff.assert_called()


# ---------------------------------------------------------------------------
# Deduplication tests
# ---------------------------------------------------------------------------


class TestCustomStrategyDeduplication:
    """Records appearing in both sources are deduplicated."""

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.apply_custom_filters")
    @patch("splintarr.services.search_queue.decrypt_api_key")
    @patch("splintarr.services.search_queue.SonarrClient")
    @patch("splintarr.services.search_queue.ExclusionService")
    async def test_duplicate_records_are_removed(
        self,
        mock_exclusion_cls,
        mock_sonarr_cls,
        mock_decrypt,
        mock_apply_filters,
        queue_manager,
        mock_db_session,
        mock_queue,
        mock_instance,
    ):
        """Same (seriesId, id) pair from both sources should appear only once."""
        mock_decrypt.return_value = "test_api_key"
        mock_queue.filters = json.dumps({"sources": ["missing", "cutoff_unmet"]})

        shared_record = _make_record(1, 10)
        unique_record = _make_record(2, 20)

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get_wanted_missing.return_value = _api_page([
            shared_record,
            unique_record,
        ])
        # Return the same shared_record from cutoff too
        mock_client.get_wanted_cutoff.return_value = _api_page([
            shared_record,
        ])
        mock_client.search_episodes.return_value = {"id": 999}
        mock_sonarr_cls.return_value = mock_client

        mock_exclusion = MagicMock()
        mock_exclusion.get_active_exclusion_keys.return_value = set()
        mock_exclusion_cls.return_value = mock_exclusion

        mock_db_session.query.return_value.filter.return_value.all.return_value = []

        # Capture what apply_custom_filters receives
        mock_apply_filters.return_value = []  # return empty to keep test simple

        await queue_manager._execute_custom_strategy(
            queue=mock_queue,
            instance=mock_instance,
            db=mock_db_session,
        )

        # apply_custom_filters should have received exactly 2 records (deduped)
        mock_apply_filters.assert_called_once()
        records_arg = mock_apply_filters.call_args[0][0]
        assert len(records_arg) == 2


# ---------------------------------------------------------------------------
# Filter application tests
# ---------------------------------------------------------------------------


class TestCustomStrategyFilterApplication:
    """Verifies apply_custom_filters is called with correct arguments."""

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.apply_custom_filters")
    @patch("splintarr.services.search_queue.decrypt_api_key")
    @patch("splintarr.services.search_queue.SonarrClient")
    @patch("splintarr.services.search_queue.ExclusionService")
    async def test_apply_custom_filters_receives_records_and_filters(
        self,
        mock_exclusion_cls,
        mock_sonarr_cls,
        mock_decrypt,
        mock_apply_filters,
        queue_manager,
        mock_db_session,
        mock_queue,
        mock_instance,
    ):
        """apply_custom_filters should be called with (records, library_items, filters)."""
        mock_decrypt.return_value = "test_api_key"
        filters_dict = {
            "sources": ["missing"],
            "year_min": 2000,
            "quality_profiles": ["HD-1080p"],
        }
        mock_queue.filters = json.dumps(filters_dict)

        records = [_make_record(1, 10), _make_record(2, 20)]
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get_wanted_missing.return_value = _api_page(records)
        mock_client.search_episodes.return_value = {"id": 999}
        mock_sonarr_cls.return_value = mock_client

        mock_exclusion = MagicMock()
        mock_exclusion.get_active_exclusion_keys.return_value = set()
        mock_exclusion_cls.return_value = mock_exclusion

        # Library items
        lib_item = _FakeLibraryItem(id=1, external_id=1, instance_id=1)

        # The db.query() chain is called for both LibraryItem and LibraryEpisode.
        # First call (LibraryItem) returns our item; second call (LibraryEpisode) returns [].
        query_mock = MagicMock()
        filter_mock_1 = MagicMock()
        filter_mock_1.all.return_value = [lib_item]
        filter_mock_2 = MagicMock()
        filter_mock_2.all.return_value = []
        query_mock.filter.side_effect = [filter_mock_1, filter_mock_2]
        mock_db_session.query.return_value = query_mock

        # Passthrough: return the same records from filter
        mock_apply_filters.return_value = records

        await queue_manager._execute_custom_strategy(
            queue=mock_queue,
            instance=mock_instance,
            db=mock_db_session,
        )

        mock_apply_filters.assert_called_once()
        call_args = mock_apply_filters.call_args[0]
        # arg0: records
        assert len(call_args[0]) == 2
        # arg1: library_items dict
        assert isinstance(call_args[1], dict)
        assert lib_item.external_id in call_args[1]
        # arg2: filters dict
        assert call_args[2] == filters_dict


# ---------------------------------------------------------------------------
# Pipeline integration tests
# ---------------------------------------------------------------------------


class TestCustomStrategyPipeline:
    """Filtered records go through the standard scoring/search pipeline."""

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.apply_custom_filters")
    @patch("splintarr.services.search_queue.decrypt_api_key")
    @patch("splintarr.services.search_queue.SonarrClient")
    @patch("splintarr.services.search_queue.ExclusionService")
    async def test_filtered_records_are_searched(
        self,
        mock_exclusion_cls,
        mock_sonarr_cls,
        mock_decrypt,
        mock_apply_filters,
        queue_manager,
        mock_db_session,
        mock_queue,
        mock_instance,
    ):
        """Records passing custom filters should be searched via the pipeline."""
        mock_decrypt.return_value = "test_api_key"
        mock_queue.filters = json.dumps({"sources": ["missing"], "year_min": 2000})

        records = [_make_record(1, 10), _make_record(2, 20)]
        # Filter keeps only the first record
        mock_apply_filters.return_value = [records[0]]

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get_wanted_missing.return_value = _api_page(records)
        mock_client.search_episodes.return_value = {"id": 999}
        mock_sonarr_cls.return_value = mock_client

        mock_exclusion = MagicMock()
        mock_exclusion.get_active_exclusion_keys.return_value = set()
        mock_exclusion_cls.return_value = mock_exclusion

        mock_db_session.query.return_value.filter.return_value.all.return_value = []

        result = await queue_manager._execute_custom_strategy(
            queue=mock_queue,
            instance=mock_instance,
            db=mock_db_session,
        )

        # Pipeline should have evaluated only the 1 filtered record
        assert result["items_evaluated"] == 1
        assert result["status"] in ("success", "partial_success")

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.apply_custom_filters")
    @patch("splintarr.services.search_queue.decrypt_api_key")
    @patch("splintarr.services.search_queue.SonarrClient")
    @patch("splintarr.services.search_queue.ExclusionService")
    async def test_empty_filtered_records_produce_success_with_zero_items(
        self,
        mock_exclusion_cls,
        mock_sonarr_cls,
        mock_decrypt,
        mock_apply_filters,
        queue_manager,
        mock_db_session,
        mock_queue,
        mock_instance,
    ):
        """If custom filters eliminate all records, result should be success with 0 items."""
        mock_decrypt.return_value = "test_api_key"
        mock_queue.filters = json.dumps({"sources": ["missing"], "year_min": 3000})

        records = [_make_record(1, 10)]
        mock_apply_filters.return_value = []  # All filtered out

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get_wanted_missing.return_value = _api_page(records)
        mock_sonarr_cls.return_value = mock_client

        mock_exclusion = MagicMock()
        mock_exclusion.get_active_exclusion_keys.return_value = set()
        mock_exclusion_cls.return_value = mock_exclusion

        mock_db_session.query.return_value.filter.return_value.all.return_value = []

        result = await queue_manager._execute_custom_strategy(
            queue=mock_queue,
            instance=mock_instance,
            db=mock_db_session,
        )

        assert result["status"] == "success"
        assert result["items_evaluated"] == 0
        assert result["items_searched"] == 0


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestCustomStrategyErrors:
    """Error handling in the custom strategy."""

    @pytest.mark.asyncio
    async def test_invalid_json_filters_raises_error(
        self,
        queue_manager,
        mock_db_session,
        mock_queue,
        mock_instance,
    ):
        """Invalid JSON in queue.filters should raise SearchQueueError."""
        mock_queue.filters = "not valid json {{"

        with pytest.raises(SearchQueueError, match="Invalid custom filters JSON"):
            await queue_manager._execute_custom_strategy(
                queue=mock_queue,
                instance=mock_instance,
                db=mock_db_session,
            )

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.decrypt_api_key")
    @patch("splintarr.services.search_queue.SonarrClient")
    @patch("splintarr.services.search_queue.ExclusionService")
    async def test_default_sources_when_not_specified(
        self,
        mock_exclusion_cls,
        mock_sonarr_cls,
        mock_decrypt,
        queue_manager,
        mock_db_session,
        mock_queue,
        mock_instance,
    ):
        """When sources is not in filters, default to ['missing']."""
        mock_decrypt.return_value = "test_api_key"
        mock_queue.filters = json.dumps({"year_min": 2000})  # No sources key

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get_wanted_missing.return_value = _api_page([])
        mock_sonarr_cls.return_value = mock_client

        mock_exclusion = MagicMock()
        mock_exclusion.get_active_exclusion_keys.return_value = set()
        mock_exclusion_cls.return_value = mock_exclusion

        mock_db_session.query.return_value.filter.return_value.all.return_value = []

        result = await queue_manager._execute_custom_strategy(
            queue=mock_queue,
            instance=mock_instance,
            db=mock_db_session,
        )

        mock_client.get_wanted_missing.assert_called()
        assert result["status"] == "success"

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.decrypt_api_key")
    @patch("splintarr.services.search_queue.SonarrClient")
    @patch("splintarr.services.search_queue.ExclusionService")
    async def test_null_filters_defaults_to_missing(
        self,
        mock_exclusion_cls,
        mock_sonarr_cls,
        mock_decrypt,
        queue_manager,
        mock_db_session,
        mock_queue,
        mock_instance,
    ):
        """When queue.filters is None, default to missing source."""
        mock_decrypt.return_value = "test_api_key"
        mock_queue.filters = None  # No filters at all

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get_wanted_missing.return_value = _api_page([])
        mock_sonarr_cls.return_value = mock_client

        mock_exclusion = MagicMock()
        mock_exclusion.get_active_exclusion_keys.return_value = set()
        mock_exclusion_cls.return_value = mock_exclusion

        mock_db_session.query.return_value.filter.return_value.all.return_value = []

        result = await queue_manager._execute_custom_strategy(
            queue=mock_queue,
            instance=mock_instance,
            db=mock_db_session,
        )

        mock_client.get_wanted_missing.assert_called()
        assert result["status"] == "success"
