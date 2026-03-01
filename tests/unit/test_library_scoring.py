"""
Unit tests for LibraryItem search intelligence columns and helper methods.

Tests the scoring/feedback columns (search_attempts, last_searched_at,
grabs_confirmed, last_grab_at) and the record_search(), record_grab(),
grab_rate, and consecutive_failures helpers added in v0.3.0.
"""

from datetime import datetime
from unittest.mock import patch

import pytest

from splintarr.models.instance import Instance
from splintarr.models.library import LibraryItem
from splintarr.models.user import User


@pytest.fixture()
def instance(db_session):
    """Create a User + Instance required by LibraryItem FK."""
    user = User(username="scorer", password_hash="hash")
    db_session.add(user)
    db_session.commit()

    inst = Instance(
        user_id=user.id,
        name="Test Sonarr",
        instance_type="sonarr",
        url="https://sonarr.example.com",
        api_key="key",
    )
    db_session.add(inst)
    db_session.commit()
    return inst


def _make_item(db_session, instance, **overrides):
    """Helper to create a LibraryItem with sensible defaults."""
    defaults = {
        "instance_id": instance.id,
        "content_type": "series",
        "external_id": 100,
        "title": "Test Series",
        "year": 2024,
        "episode_count": 10,
        "episode_have": 5,
    }
    defaults.update(overrides)
    item = LibraryItem(**defaults)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


class TestScoringColumnDefaults:
    """New columns have correct default values after insert."""

    def test_search_attempts_defaults_to_zero(self, db_session, instance):
        item = _make_item(db_session, instance)
        assert item.search_attempts == 0

    def test_last_searched_at_defaults_to_none(self, db_session, instance):
        item = _make_item(db_session, instance)
        assert item.last_searched_at is None

    def test_grabs_confirmed_defaults_to_zero(self, db_session, instance):
        item = _make_item(db_session, instance)
        assert item.grabs_confirmed == 0

    def test_last_grab_at_defaults_to_none(self, db_session, instance):
        item = _make_item(db_session, instance)
        assert item.last_grab_at is None


class TestRecordSearch:
    """Tests for record_search() helper."""

    def test_increments_search_attempts(self, db_session, instance):
        item = _make_item(db_session, instance)
        item.record_search()
        db_session.commit()
        db_session.refresh(item)

        assert item.search_attempts == 1

    def test_sets_last_searched_at(self, db_session, instance):
        item = _make_item(db_session, instance)
        item.record_search()
        db_session.commit()
        db_session.refresh(item)

        assert item.last_searched_at is not None
        assert isinstance(item.last_searched_at, datetime)

    def test_multiple_calls_increment_correctly(self, db_session, instance):
        item = _make_item(db_session, instance)
        item.record_search()
        item.record_search()
        item.record_search()
        db_session.commit()
        db_session.refresh(item)

        assert item.search_attempts == 3

    def test_last_searched_at_updates_on_each_call(self, db_session, instance):
        item = _make_item(db_session, instance)

        fixed_time_1 = datetime(2026, 1, 1, 12, 0, 0)
        fixed_time_2 = datetime(2026, 1, 2, 12, 0, 0)

        with patch("splintarr.models.library.datetime") as mock_dt:
            mock_dt.utcnow.return_value = fixed_time_1
            item.record_search()

        with patch("splintarr.models.library.datetime") as mock_dt:
            mock_dt.utcnow.return_value = fixed_time_2
            item.record_search()

        db_session.commit()
        db_session.refresh(item)

        assert item.last_searched_at == fixed_time_2


class TestRecordGrab:
    """Tests for record_grab() helper."""

    def test_increments_grabs_confirmed(self, db_session, instance):
        item = _make_item(db_session, instance)
        item.record_grab()
        db_session.commit()
        db_session.refresh(item)

        assert item.grabs_confirmed == 1

    def test_sets_last_grab_at(self, db_session, instance):
        item = _make_item(db_session, instance)
        item.record_grab()
        db_session.commit()
        db_session.refresh(item)

        assert item.last_grab_at is not None
        assert isinstance(item.last_grab_at, datetime)

    def test_multiple_calls_increment_correctly(self, db_session, instance):
        item = _make_item(db_session, instance)
        item.record_grab()
        item.record_grab()
        db_session.commit()
        db_session.refresh(item)

        assert item.grabs_confirmed == 2


class TestGrabRate:
    """Tests for grab_rate property."""

    def test_zero_attempts_returns_zero(self, db_session, instance):
        item = _make_item(db_session, instance)
        assert item.grab_rate == 0.0

    def test_five_attempts_two_grabs(self, db_session, instance):
        item = _make_item(db_session, instance, search_attempts=5, grabs_confirmed=2)
        db_session.commit()
        db_session.refresh(item)

        assert item.grab_rate == pytest.approx(0.4)

    def test_all_grabs_returns_one(self, db_session, instance):
        item = _make_item(db_session, instance, search_attempts=3, grabs_confirmed=3)
        db_session.commit()
        db_session.refresh(item)

        assert item.grab_rate == pytest.approx(1.0)

    def test_no_grabs_returns_zero(self, db_session, instance):
        item = _make_item(db_session, instance, search_attempts=5, grabs_confirmed=0)
        db_session.commit()
        db_session.refresh(item)

        assert item.grab_rate == 0.0


class TestConsecutiveFailures:
    """Tests for consecutive_failures property."""

    def test_five_attempts_two_grabs_returns_three(self, db_session, instance):
        item = _make_item(db_session, instance, search_attempts=5, grabs_confirmed=2)
        db_session.commit()
        db_session.refresh(item)

        assert item.consecutive_failures == 3

    def test_zero_attempts_returns_zero(self, db_session, instance):
        item = _make_item(db_session, instance)
        assert item.consecutive_failures == 0

    def test_equal_attempts_and_grabs_returns_zero(self, db_session, instance):
        item = _make_item(db_session, instance, search_attempts=4, grabs_confirmed=4)
        db_session.commit()
        db_session.refresh(item)

        assert item.consecutive_failures == 0

    def test_never_negative(self, db_session, instance):
        """Even if data is somehow inconsistent, consecutive_failures >= 0."""
        item = _make_item(db_session, instance, search_attempts=1, grabs_confirmed=5)
        db_session.commit()
        db_session.refresh(item)

        assert item.consecutive_failures == 0
