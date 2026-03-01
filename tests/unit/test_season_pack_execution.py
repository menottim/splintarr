"""
Unit tests for Season Pack Search Execution Logic (v0.4.0 - Task 5).

Tests cover:
- _group_by_season: pure function for grouping Sonarr records by (seriesId, seasonNumber)
- Season pack integration: splitting packs from singles during search execution
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from splintarr.services.search_queue import _group_by_season

# ---------------------------------------------------------------------------
# _group_by_season pure function tests
# ---------------------------------------------------------------------------


class TestGroupBySeason:
    """Tests for the _group_by_season grouping function."""

    def test_group_by_season_basic(self):
        """3 episodes from same series/season grouped together."""
        records = [
            {"id": 101, "seriesId": 1, "seasonNumber": 2, "title": "Ep1"},
            {"id": 102, "seriesId": 1, "seasonNumber": 2, "title": "Ep2"},
            {"id": 103, "seriesId": 1, "seasonNumber": 2, "title": "Ep3"},
        ]

        result = _group_by_season(records)

        assert len(result) == 1
        assert (1, 2) in result
        assert len(result[(1, 2)]) == 3
        assert result[(1, 2)][0]["id"] == 101
        assert result[(1, 2)][1]["id"] == 102
        assert result[(1, 2)][2]["id"] == 103

    def test_group_by_season_multiple_series(self):
        """Episodes from different series are separated into different groups."""
        records = [
            {"id": 1, "seriesId": 10, "seasonNumber": 1},
            {"id": 2, "seriesId": 10, "seasonNumber": 1},
            {"id": 3, "seriesId": 20, "seasonNumber": 3},
            {"id": 4, "seriesId": 20, "seasonNumber": 3},
            {"id": 5, "seriesId": 10, "seasonNumber": 2},
        ]

        result = _group_by_season(records)

        assert len(result) == 3
        assert len(result[(10, 1)]) == 2
        assert len(result[(20, 3)]) == 2
        assert len(result[(10, 2)]) == 1

    def test_group_by_season_missing_fields(self):
        """Records without seriesId or seasonNumber are skipped."""
        records = [
            {"id": 1, "seriesId": 10, "seasonNumber": 1},  # valid
            {"id": 2, "seasonNumber": 1},  # missing seriesId
            {"id": 3, "seriesId": 10},  # missing seasonNumber
            {"id": 4},  # missing both
            {"id": 5, "seriesId": None, "seasonNumber": 1},  # explicit None seriesId
            {"id": 6, "seriesId": 10, "seasonNumber": None},  # explicit None season
        ]

        result = _group_by_season(records)

        assert len(result) == 1
        assert (10, 1) in result
        assert len(result[(10, 1)]) == 1
        assert result[(10, 1)][0]["id"] == 1

    def test_group_by_season_empty_list(self):
        """Empty input returns empty dict."""
        result = _group_by_season([])
        assert result == {}

    def test_group_by_season_preserves_record_data(self):
        """Grouped records retain all original fields."""
        records = [
            {
                "id": 42,
                "seriesId": 7,
                "seasonNumber": 3,
                "title": "My Episode",
                "series": {"title": "My Show"},
                "episodeNumber": 5,
            },
        ]

        result = _group_by_season(records)
        grouped_record = result[(7, 3)][0]

        assert grouped_record["id"] == 42
        assert grouped_record["title"] == "My Episode"
        assert grouped_record["series"]["title"] == "My Show"
        assert grouped_record["episodeNumber"] == 5


# ---------------------------------------------------------------------------
# Season pack split logic (integration with _search_paginated_records)
# ---------------------------------------------------------------------------


class TestSeasonPackSplitLogic:
    """Test that season pack grouping correctly splits packs from singles."""

    def test_splits_packs_from_singles(self):
        """Groups above threshold become packs; groups below stay as singles.

        Given threshold=3:
        - Series 1 Season 1 has 4 episodes -> season pack
        - Series 2 Season 1 has 2 episodes -> individual searches
        - Series 1 Season 2 has 1 episode  -> individual search
        """
        records = [
            # Series 1, Season 1: 4 episodes (>= threshold of 3)
            {"id": 101, "seriesId": 1, "seasonNumber": 1},
            {"id": 102, "seriesId": 1, "seasonNumber": 1},
            {"id": 103, "seriesId": 1, "seasonNumber": 1},
            {"id": 104, "seriesId": 1, "seasonNumber": 1},
            # Series 2, Season 1: 2 episodes (< threshold of 3)
            {"id": 201, "seriesId": 2, "seasonNumber": 1},
            {"id": 202, "seriesId": 2, "seasonNumber": 1},
            # Series 1, Season 2: 1 episode (< threshold of 3)
            {"id": 105, "seriesId": 1, "seasonNumber": 2},
        ]

        threshold = 3
        groups = _group_by_season(records)

        season_pack_ids: set[int] = set()
        individual_ids: set[int] = set()

        for (_series_id, _season_number), group_records in groups.items():
            if len(group_records) >= threshold:
                # This group qualifies for season pack search
                for rec in group_records:
                    season_pack_ids.add(rec["id"])
            else:
                # These stay as individual searches
                for rec in group_records:
                    individual_ids.add(rec["id"])

        # Series 1, Season 1 episodes should be in season pack
        assert season_pack_ids == {101, 102, 103, 104}
        # Others should remain as individuals
        assert individual_ids == {201, 202, 105}

    def test_threshold_exact_boundary(self):
        """Group with exactly threshold episodes qualifies as season pack."""
        records = [
            {"id": 1, "seriesId": 10, "seasonNumber": 1},
            {"id": 2, "seriesId": 10, "seasonNumber": 1},
            {"id": 3, "seriesId": 10, "seasonNumber": 1},
        ]

        threshold = 3
        groups = _group_by_season(records)

        # Exactly 3 episodes with threshold 3 -> qualifies as pack
        assert len(groups[(10, 1)]) == threshold
        assert len(groups[(10, 1)]) >= threshold

    def test_threshold_one_below(self):
        """Group with one fewer than threshold does NOT qualify."""
        records = [
            {"id": 1, "seriesId": 10, "seasonNumber": 1},
            {"id": 2, "seriesId": 10, "seasonNumber": 1},
        ]

        threshold = 3
        groups = _group_by_season(records)

        assert len(groups[(10, 1)]) == 2
        assert len(groups[(10, 1)]) < threshold


# ---------------------------------------------------------------------------
# Integration: _search_paginated_records with season packs enabled
# ---------------------------------------------------------------------------


class TestSeasonPackSearchExecution:
    """Integration tests for season pack search within _search_paginated_records."""

    @pytest.fixture
    def mock_db_session(self):
        """Mock database session."""
        session = MagicMock()
        session.query = MagicMock()
        session.add = MagicMock()
        session.commit = MagicMock()
        session.close = MagicMock()
        return session

    @pytest.fixture
    def mock_session_factory(self, mock_db_session):
        """Mock session factory."""
        return lambda: mock_db_session

    @pytest.fixture
    def queue_manager(self, mock_session_factory):
        """Create queue manager instance."""
        from splintarr.services.search_queue import SearchQueueManager

        return SearchQueueManager(mock_session_factory)

    @pytest.fixture
    def sonarr_instance(self):
        """Create a mock Sonarr instance."""
        instance = MagicMock()
        instance.id = 1
        instance.user_id = 1
        instance.instance_type = "sonarr"
        instance.url = "https://sonarr.example.com"
        instance.api_key = "encrypted_key"
        instance.verify_ssl = True
        instance.rate_limit_per_second = 5
        return instance

    @pytest.fixture
    def season_pack_queue(self):
        """Create a mock queue with season pack enabled."""
        queue = MagicMock()
        queue.id = 1
        queue.instance_id = 1
        queue.name = "Season Pack Test"
        queue.strategy = "missing"
        queue.season_pack_enabled = True
        queue.season_pack_threshold = 3
        queue.cooldown_mode = "adaptive"
        queue.cooldown_hours = None
        queue.max_items_per_run = 50
        return queue

    @pytest.fixture
    def disabled_pack_queue(self):
        """Create a mock queue with season pack disabled."""
        queue = MagicMock()
        queue.id = 2
        queue.instance_id = 1
        queue.name = "No Season Pack"
        queue.strategy = "missing"
        queue.season_pack_enabled = False
        queue.season_pack_threshold = 3
        queue.cooldown_mode = "adaptive"
        queue.cooldown_hours = None
        queue.max_items_per_run = 50
        return queue

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.ExclusionService")
    @patch("splintarr.services.search_queue.is_in_cooldown", return_value=False)
    @patch("splintarr.services.search_queue.compute_score", return_value=(50.0, "default"))
    @patch("splintarr.services.search_queue.decrypt_api_key", return_value="test_key")
    @patch("splintarr.services.search_queue.SonarrClient")
    async def test_season_pack_triggers_season_search(
        self,
        mock_sonarr_cls,
        mock_decrypt,
        mock_score,
        mock_cooldown,
        mock_exclusion_cls,
        queue_manager,
        season_pack_queue,
        sonarr_instance,
        mock_db_session,
    ):
        """When season_pack_enabled and >= threshold episodes in same season,
        season_search is called instead of individual episode searches."""
        # Setup exclusion service to return no exclusions
        mock_exclusion_service = MagicMock()
        mock_exclusion_service.get_active_exclusion_keys.return_value = set()
        mock_exclusion_cls.return_value = mock_exclusion_service

        # Setup mock client
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        # 4 episodes from series 10, season 2 (>= threshold of 3)
        mock_client.get_wanted_missing.return_value = {
            "records": [
                {
                    "id": 1,
                    "seriesId": 10,
                    "seasonNumber": 2,
                    "series": {"title": "Test Show", "id": 10},
                    "episodeNumber": 1,
                    "title": "Ep 1",
                },
                {
                    "id": 2,
                    "seriesId": 10,
                    "seasonNumber": 2,
                    "series": {"title": "Test Show", "id": 10},
                    "episodeNumber": 2,
                    "title": "Ep 2",
                },
                {
                    "id": 3,
                    "seriesId": 10,
                    "seasonNumber": 2,
                    "series": {"title": "Test Show", "id": 10},
                    "episodeNumber": 3,
                    "title": "Ep 3",
                },
                {
                    "id": 4,
                    "seriesId": 10,
                    "seasonNumber": 2,
                    "series": {"title": "Test Show", "id": 10},
                    "episodeNumber": 4,
                    "title": "Ep 4",
                },
            ],
            "totalRecords": 4,
        }
        mock_client.season_search.return_value = {
            "id": 999,
            "name": "SeasonSearch",
            "status": "queued",
        }
        mock_client.search_episodes.return_value = {"id": 123}
        mock_sonarr_cls.return_value = mock_client

        # Mock library items (keyed by external_id = seriesId for Sonarr)
        mock_library_item = MagicMock()
        mock_library_item.record_search = MagicMock()
        queue_manager._load_library_items = MagicMock(return_value={10: mock_library_item})

        # Mock rate limit to always allow
        queue_manager._check_rate_limit = AsyncMock(return_value=True)

        result = await queue_manager._search_paginated_records(
            queue=season_pack_queue,
            instance=sonarr_instance,
            db=mock_db_session,
            fetch_method="get_wanted_missing",
            strategy_name="missing",
        )

        # season_search should have been called once for (seriesId=10, season=2)
        mock_client.season_search.assert_called_once_with(
            series_id=10, season_number=2
        )

        # Individual search_episodes should NOT have been called for these episodes
        mock_client.search_episodes.assert_not_called()

        # Library item should have had record_search called
        mock_library_item.record_search.assert_called()

        # Result should reflect that searches were triggered
        assert result["searches_triggered"] >= 1
        assert result["status"] == "success"

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.ExclusionService")
    @patch("splintarr.services.search_queue.is_in_cooldown", return_value=False)
    @patch("splintarr.services.search_queue.compute_score", return_value=(50.0, "default"))
    @patch("splintarr.services.search_queue.decrypt_api_key", return_value="test_key")
    @patch("splintarr.services.search_queue.SonarrClient")
    async def test_below_threshold_uses_individual_search(
        self,
        mock_sonarr_cls,
        mock_decrypt,
        mock_score,
        mock_cooldown,
        mock_exclusion_cls,
        queue_manager,
        season_pack_queue,
        sonarr_instance,
        mock_db_session,
    ):
        """When season_pack_enabled but fewer than threshold episodes in a season,
        individual episode searches are used instead."""
        mock_exclusion_service = MagicMock()
        mock_exclusion_service.get_active_exclusion_keys.return_value = set()
        mock_exclusion_cls.return_value = mock_exclusion_service

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        # Only 2 episodes from series 10, season 2 (< threshold of 3)
        mock_client.get_wanted_missing.return_value = {
            "records": [
                {
                    "id": 1,
                    "seriesId": 10,
                    "seasonNumber": 2,
                    "series": {"title": "Test Show", "id": 10},
                    "episodeNumber": 1,
                    "title": "Ep 1",
                },
                {
                    "id": 2,
                    "seriesId": 10,
                    "seasonNumber": 2,
                    "series": {"title": "Test Show", "id": 10},
                    "episodeNumber": 2,
                    "title": "Ep 2",
                },
            ],
            "totalRecords": 2,
        }
        mock_client.search_episodes.return_value = {"id": 123}
        mock_sonarr_cls.return_value = mock_client

        mock_library_item = MagicMock()
        mock_library_item.record_search = MagicMock()
        queue_manager._load_library_items = MagicMock(return_value={10: mock_library_item})
        queue_manager._check_rate_limit = AsyncMock(return_value=True)

        result = await queue_manager._search_paginated_records(
            queue=season_pack_queue,
            instance=sonarr_instance,
            db=mock_db_session,
            fetch_method="get_wanted_missing",
            strategy_name="missing",
        )

        # season_search should NOT have been called
        mock_client.season_search.assert_not_called()

        # Individual searches should have been called for each episode
        assert mock_client.search_episodes.call_count == 2
        assert result["status"] == "success"

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.ExclusionService")
    @patch("splintarr.services.search_queue.is_in_cooldown", return_value=False)
    @patch("splintarr.services.search_queue.compute_score", return_value=(50.0, "default"))
    @patch("splintarr.services.search_queue.decrypt_api_key", return_value="test_key")
    @patch("splintarr.services.search_queue.SonarrClient")
    async def test_disabled_season_pack_uses_individual_search(
        self,
        mock_sonarr_cls,
        mock_decrypt,
        mock_score,
        mock_cooldown,
        mock_exclusion_cls,
        queue_manager,
        disabled_pack_queue,
        sonarr_instance,
        mock_db_session,
    ):
        """When season_pack_enabled=False, all searches are individual even if
        threshold would be met."""
        mock_exclusion_service = MagicMock()
        mock_exclusion_service.get_active_exclusion_keys.return_value = set()
        mock_exclusion_cls.return_value = mock_exclusion_service

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        # 4 episodes from same season (would qualify for pack if enabled)
        mock_client.get_wanted_missing.return_value = {
            "records": [
                {
                    "id": i,
                    "seriesId": 10,
                    "seasonNumber": 1,
                    "series": {"title": "Test Show", "id": 10},
                    "episodeNumber": i,
                    "title": f"Ep {i}",
                }
                for i in range(1, 5)
            ],
            "totalRecords": 4,
        }
        mock_client.search_episodes.return_value = {"id": 123}
        mock_sonarr_cls.return_value = mock_client

        mock_library_item = MagicMock()
        mock_library_item.record_search = MagicMock()
        queue_manager._load_library_items = MagicMock(return_value={10: mock_library_item})
        queue_manager._check_rate_limit = AsyncMock(return_value=True)

        result = await queue_manager._search_paginated_records(
            queue=disabled_pack_queue,
            instance=sonarr_instance,
            db=mock_db_session,
            fetch_method="get_wanted_missing",
            strategy_name="missing",
        )

        # season_search should NOT have been called (feature disabled)
        mock_client.season_search.assert_not_called()

        # All 4 episodes searched individually
        assert mock_client.search_episodes.call_count == 4
        assert result["status"] == "success"

    @pytest.mark.asyncio
    @patch("splintarr.services.search_queue.ExclusionService")
    @patch("splintarr.services.search_queue.is_in_cooldown", return_value=False)
    @patch("splintarr.services.search_queue.compute_score", return_value=(50.0, "default"))
    @patch("splintarr.services.search_queue.decrypt_api_key", return_value="test_key")
    @patch("splintarr.services.search_queue.SonarrClient")
    async def test_mixed_packs_and_singles(
        self,
        mock_sonarr_cls,
        mock_decrypt,
        mock_score,
        mock_cooldown,
        mock_exclusion_cls,
        queue_manager,
        season_pack_queue,
        sonarr_instance,
        mock_db_session,
    ):
        """Mix of season pack and individual searches in same execution."""
        mock_exclusion_service = MagicMock()
        mock_exclusion_service.get_active_exclusion_keys.return_value = set()
        mock_exclusion_cls.return_value = mock_exclusion_service

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        records = [
            # Series 10, Season 1: 3 episodes (= threshold) -> pack
            {
                "id": 1,
                "seriesId": 10,
                "seasonNumber": 1,
                "series": {"title": "Show A", "id": 10},
                "episodeNumber": 1,
                "title": "A S01E01",
            },
            {
                "id": 2,
                "seriesId": 10,
                "seasonNumber": 1,
                "series": {"title": "Show A", "id": 10},
                "episodeNumber": 2,
                "title": "A S01E02",
            },
            {
                "id": 3,
                "seriesId": 10,
                "seasonNumber": 1,
                "series": {"title": "Show A", "id": 10},
                "episodeNumber": 3,
                "title": "A S01E03",
            },
            # Series 20, Season 5: 1 episode -> individual
            {
                "id": 4,
                "seriesId": 20,
                "seasonNumber": 5,
                "series": {"title": "Show B", "id": 20},
                "episodeNumber": 1,
                "title": "B S05E01",
            },
        ]

        mock_client.get_wanted_missing.return_value = {
            "records": records,
            "totalRecords": 4,
        }
        mock_client.season_search.return_value = {
            "id": 999,
            "name": "SeasonSearch",
            "status": "queued",
        }
        mock_client.search_episodes.return_value = {"id": 123}
        mock_sonarr_cls.return_value = mock_client

        mock_lib_item_10 = MagicMock()
        mock_lib_item_10.record_search = MagicMock()
        mock_lib_item_20 = MagicMock()
        mock_lib_item_20.record_search = MagicMock()
        queue_manager._load_library_items = MagicMock(
            return_value={10: mock_lib_item_10, 20: mock_lib_item_20}
        )
        queue_manager._check_rate_limit = AsyncMock(return_value=True)

        result = await queue_manager._search_paginated_records(
            queue=season_pack_queue,
            instance=sonarr_instance,
            db=mock_db_session,
            fetch_method="get_wanted_missing",
            strategy_name="missing",
        )

        # season_search called once for series 10, season 1
        mock_client.season_search.assert_called_once_with(
            series_id=10, season_number=1
        )

        # Individual search called once for the single episode (series 20)
        assert mock_client.search_episodes.call_count == 1
        mock_client.search_episodes.assert_called_with([4])

        assert result["status"] == "success"
        assert result["searches_triggered"] >= 2  # 1 season pack + 1 individual
