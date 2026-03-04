"""Tests for library completion data."""
import pytest
from unittest.mock import MagicMock

from splintarr.api.library import _get_completion_data


def _make_item(id, title, year, ep_count, ep_have, status="ended", added_at="2025-01-01", poster_path=None):
    item = MagicMock()
    item.id = id
    item.title = title
    item.year = year
    item.episode_count = ep_count
    item.episode_have = ep_have
    item.poster_path = poster_path
    item.status = status
    item.added_at = added_at
    type(item).completion_pct = property(
        lambda self: round(self.episode_have / self.episode_count * 100, 1) if self.episode_count > 0 else 0.0
    )
    return item


class TestGetCompletionData:
    def test_most_incomplete_sorted_ascending(self):
        items = [
            _make_item(1, "A", 2020, 10, 8),  # 80%
            _make_item(2, "B", 2021, 50, 5),  # 10%
            _make_item(3, "C", 2022, 20, 20),  # 100% — excluded
        ]
        result = _get_completion_data(items)
        assert len(result["most_incomplete"]) == 2
        assert result["most_incomplete"][0]["title"] == "B"
        assert result["most_incomplete"][1]["title"] == "A"

    def test_closest_to_complete_sorted_descending(self):
        items = [
            _make_item(1, "A", 2020, 10, 6),  # 60%
            _make_item(2, "B", 2021, 10, 9),  # 90%
            _make_item(3, "C", 2022, 10, 2),  # 20% — below 50%
        ]
        result = _get_completion_data(items)
        assert len(result["closest_to_complete"]) == 2
        assert result["closest_to_complete"][0]["title"] == "B"
        assert result["closest_to_complete"][1]["title"] == "A"

    def test_complete_items_excluded(self):
        items = [_make_item(1, "Done", 2020, 10, 10)]
        result = _get_completion_data(items)
        assert len(result["most_incomplete"]) == 0
        assert len(result["closest_to_complete"]) == 0
        assert len(result["recently_aired"]) == 0

    def test_recently_aired_sorted_by_added_at_desc(self):
        items = [
            _make_item(1, "Old", 2020, 10, 5, added_at="2024-01-01"),
            _make_item(2, "New", 2025, 10, 3, added_at="2025-06-01"),
        ]
        result = _get_completion_data(items)
        assert result["recently_aired"][0]["title"] == "New"

    def test_lists_limited_to_10(self):
        items = [_make_item(i, f"S{i}", 2020, 100, i * 3) for i in range(1, 16)]
        result = _get_completion_data(items)
        assert len(result["most_incomplete"]) <= 10

    def test_zero_episode_count_excluded(self):
        items = [_make_item(1, "Empty", 2020, 0, 0)]
        result = _get_completion_data(items)
        assert len(result["most_incomplete"]) == 0
