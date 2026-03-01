"""
Unit tests for the cooldown service (splintarr.services.cooldown).

Tests tiered adaptive cooldown, flat cooldown, exponential backoff,
cap enforcement, and edge cases.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from splintarr.services.cooldown import (
    MAX_COOLDOWN_HOURS,
    get_effective_cooldown_hours,
    is_in_cooldown,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_record(
    air_date: datetime | None = None,
    added: datetime | None = None,
) -> dict:
    """Build a minimal wanted-API record dict."""
    rec: dict = {}
    if air_date is not None:
        rec["airDateUtc"] = air_date.isoformat() + "Z"
    if added is not None:
        rec["added"] = added.isoformat() + "Z"
    return rec


def _make_library_item(
    last_searched_at: datetime | None = None,
    search_attempts: int = 0,
    grabs_confirmed: int = 0,
) -> MagicMock:
    """Build a mock LibraryItem with cooldown-relevant attributes."""
    item = MagicMock()
    item.last_searched_at = last_searched_at
    item.search_attempts = search_attempts
    item.grabs_confirmed = grabs_confirmed
    # consecutive_failures is a property: attempts - grabs
    item.consecutive_failures = max(0, search_attempts - grabs_confirmed)
    return item


# ===================================================================
# Test 1: Never searched -> not in cooldown
# ===================================================================
class TestNeverSearched:
    """Items that have never been searched are not in cooldown."""

    def test_none_library_item_not_in_cooldown(self):
        """No library item at all -> not in cooldown."""
        record = _make_record(air_date=datetime.utcnow() - timedelta(hours=6))
        assert is_in_cooldown(None, record, "adaptive", None) is False

    def test_library_item_never_searched(self):
        """Library item with last_searched_at=None -> not in cooldown."""
        item = _make_library_item(last_searched_at=None)
        record = _make_record(air_date=datetime.utcnow() - timedelta(hours=6))
        assert is_in_cooldown(item, record, "adaptive", None) is False

    def test_none_library_item_flat_mode(self):
        """No library item in flat mode -> not in cooldown."""
        record = _make_record(air_date=datetime.utcnow())
        assert is_in_cooldown(None, record, "flat", 24) is False


# ===================================================================
# Test 2-3: Flat mode cooldown
# ===================================================================
class TestFlatCooldown:
    """Flat cooldown mode uses a fixed number of hours."""

    def test_flat_within_cooldown(self):
        """Item searched 2 hours ago with 24h flat cooldown -> in cooldown."""
        item = _make_library_item(
            last_searched_at=datetime.utcnow() - timedelta(hours=2),
        )
        record = _make_record(air_date=datetime.utcnow() - timedelta(days=3))
        assert is_in_cooldown(item, record, "flat", 24) is True

    def test_flat_past_cooldown(self):
        """Item searched 25 hours ago with 24h flat cooldown -> not in cooldown."""
        item = _make_library_item(
            last_searched_at=datetime.utcnow() - timedelta(hours=25),
        )
        record = _make_record(air_date=datetime.utcnow() - timedelta(days=3))
        assert is_in_cooldown(item, record, "flat", 24) is False

    def test_flat_default_hours(self):
        """Flat mode with cooldown_hours=None defaults to 24h."""
        item = _make_library_item(
            last_searched_at=datetime.utcnow() - timedelta(hours=12),
        )
        record = _make_record(air_date=datetime.utcnow())
        assert is_in_cooldown(item, record, "flat", None) is True

    def test_flat_custom_hours(self):
        """Flat mode with cooldown_hours=6."""
        item = _make_library_item(
            last_searched_at=datetime.utcnow() - timedelta(hours=7),
        )
        record = _make_record(air_date=datetime.utcnow())
        assert is_in_cooldown(item, record, "flat", 6) is False


# ===================================================================
# Test 4-6: Adaptive tier selection based on item age
# ===================================================================
class TestAdaptiveTiers:
    """Adaptive cooldown tiers based on content age."""

    def test_item_under_24h_old_6h_cooldown(self):
        """Content < 24h old -> 6h base cooldown. Searched 5h ago -> in cooldown."""
        item = _make_library_item(
            last_searched_at=datetime.utcnow() - timedelta(hours=5),
        )
        record = _make_record(air_date=datetime.utcnow() - timedelta(hours=12))
        assert is_in_cooldown(item, record, "adaptive", None) is True

    def test_item_under_24h_old_past_cooldown(self):
        """Content < 24h old -> 6h base cooldown. Searched 7h ago -> not in cooldown."""
        item = _make_library_item(
            last_searched_at=datetime.utcnow() - timedelta(hours=7),
        )
        record = _make_record(air_date=datetime.utcnow() - timedelta(hours=12))
        assert is_in_cooldown(item, record, "adaptive", None) is False

    def test_item_under_7d_old_12h_cooldown(self):
        """Content 1-7 days old -> 12h base cooldown. Searched 10h ago -> in cooldown."""
        item = _make_library_item(
            last_searched_at=datetime.utcnow() - timedelta(hours=10),
        )
        record = _make_record(air_date=datetime.utcnow() - timedelta(days=3))
        assert is_in_cooldown(item, record, "adaptive", None) is True

    def test_item_under_7d_old_past_cooldown(self):
        """Content 1-7 days old -> 12h base cooldown. Searched 13h ago -> not in cooldown."""
        item = _make_library_item(
            last_searched_at=datetime.utcnow() - timedelta(hours=13),
        )
        record = _make_record(air_date=datetime.utcnow() - timedelta(days=3))
        assert is_in_cooldown(item, record, "adaptive", None) is False

    def test_item_over_1y_old_7d_cooldown(self):
        """Content > 1 year old -> 168h (7 day) base cooldown. Searched 5d ago -> in cooldown."""
        item = _make_library_item(
            last_searched_at=datetime.utcnow() - timedelta(days=5),
        )
        record = _make_record(air_date=datetime.utcnow() - timedelta(days=400))
        assert is_in_cooldown(item, record, "adaptive", None) is True

    def test_item_over_1y_old_past_cooldown(self):
        """Content > 1 year old -> 168h (7d) base. Searched 8d ago -> not in cooldown."""
        item = _make_library_item(
            last_searched_at=datetime.utcnow() - timedelta(days=8),
        )
        record = _make_record(air_date=datetime.utcnow() - timedelta(days=400))
        assert is_in_cooldown(item, record, "adaptive", None) is False


# ===================================================================
# Test 7: Exponential backoff with failures
# ===================================================================
class TestExponentialBackoff:
    """Consecutive failures multiply the cooldown exponentially."""

    def test_3_failures_8x_base(self):
        """3 consecutive failures -> base * 2^3 = base * 8.

        Item is 3 days old -> base 12h -> effective 96h.
        Searched 90h ago -> still in cooldown (90 < 96).
        """
        item = _make_library_item(
            last_searched_at=datetime.utcnow() - timedelta(hours=90),
            search_attempts=3,
            grabs_confirmed=0,
        )
        record = _make_record(air_date=datetime.utcnow() - timedelta(days=3))
        assert is_in_cooldown(item, record, "adaptive", None) is True

    def test_3_failures_past_backoff(self):
        """3 failures, base 12h -> effective 96h. Searched 100h ago -> not in cooldown."""
        item = _make_library_item(
            last_searched_at=datetime.utcnow() - timedelta(hours=100),
            search_attempts=3,
            grabs_confirmed=0,
        )
        record = _make_record(air_date=datetime.utcnow() - timedelta(days=3))
        assert is_in_cooldown(item, record, "adaptive", None) is False

    def test_no_failures_no_backoff(self):
        """0 failures (all grabs) -> no backoff multiplier."""
        item = _make_library_item(
            last_searched_at=datetime.utcnow() - timedelta(hours=10),
            search_attempts=5,
            grabs_confirmed=5,  # All grabbed -> consecutive_failures=0
        )
        record = _make_record(air_date=datetime.utcnow() - timedelta(days=3))
        # base 12h, no backoff -> 12h cooldown, searched 10h ago -> in cooldown
        assert is_in_cooldown(item, record, "adaptive", None) is True


# ===================================================================
# Test 8: Backoff capped at 14 days (336h)
# ===================================================================
class TestBackoffCap:
    """Exponential backoff is capped at MAX_COOLDOWN_HOURS (336h = 14 days)."""

    def test_backoff_capped(self):
        """High failure count doesn't exceed 336h cap.

        Item is <24h old -> base 6h, 10 failures -> 6*2^8=1536h
        Capped to 336h. Searched 300h ago -> still in cooldown.
        """
        item = _make_library_item(
            last_searched_at=datetime.utcnow() - timedelta(hours=300),
            search_attempts=10,
            grabs_confirmed=0,
        )
        record = _make_record(air_date=datetime.utcnow() - timedelta(hours=12))
        assert is_in_cooldown(item, record, "adaptive", None) is True

    def test_backoff_past_cap(self):
        """Past the 336h cap -> not in cooldown."""
        item = _make_library_item(
            last_searched_at=datetime.utcnow() - timedelta(hours=340),
            search_attempts=10,
            grabs_confirmed=0,
        )
        record = _make_record(air_date=datetime.utcnow() - timedelta(hours=12))
        assert is_in_cooldown(item, record, "adaptive", None) is False

    def test_max_cooldown_hours_value(self):
        """MAX_COOLDOWN_HOURS is 336 (14 days)."""
        assert MAX_COOLDOWN_HOURS == 336


# ===================================================================
# Test 9: Unknown date -> 24h default
# ===================================================================
class TestUnknownDate:
    """Items with no parseable date get a 24h default cooldown."""

    def test_no_date_fields(self):
        """Record with no date info -> 24h default. Searched 20h ago -> in cooldown."""
        item = _make_library_item(
            last_searched_at=datetime.utcnow() - timedelta(hours=20),
        )
        record: dict = {}  # No airDateUtc or added
        assert is_in_cooldown(item, record, "adaptive", None) is True

    def test_no_date_fields_past_cooldown(self):
        """Record with no date info -> 24h default. Searched 25h ago -> not in cooldown."""
        item = _make_library_item(
            last_searched_at=datetime.utcnow() - timedelta(hours=25),
        )
        record: dict = {}
        assert is_in_cooldown(item, record, "adaptive", None) is False

    def test_invalid_date_string(self):
        """Record with invalid date string -> 24h default."""
        item = _make_library_item(
            last_searched_at=datetime.utcnow() - timedelta(hours=20),
        )
        record = {"airDateUtc": "not-a-valid-date"}
        assert is_in_cooldown(item, record, "adaptive", None) is True


# ===================================================================
# Test 10: get_effective_cooldown_hours
# ===================================================================
class TestGetEffectiveCooldownHours:
    """Tests for the display/logging helper function."""

    def test_flat_mode_returns_configured_hours(self):
        """Flat mode returns configured hours."""
        assert get_effective_cooldown_hours(None, {}, "flat", 48) == 48

    def test_flat_mode_default_24(self):
        """Flat mode with no hours configured defaults to 24."""
        assert get_effective_cooldown_hours(None, {}, "flat", None) == 24

    def test_adaptive_no_library_item(self):
        """Adaptive with no library item -> base hours from record age."""
        record = _make_record(air_date=datetime.utcnow() - timedelta(hours=6))
        assert get_effective_cooldown_hours(None, record, "adaptive", None) == 6

    def test_adaptive_with_failures(self):
        """Adaptive with failures -> backoff applied."""
        item = _make_library_item(search_attempts=2, grabs_confirmed=0)
        record = _make_record(air_date=datetime.utcnow() - timedelta(days=3))
        # base 12h, 2 failures -> 12 * 2^2 = 48
        assert get_effective_cooldown_hours(item, record, "adaptive", None) == 48

    def test_adaptive_with_failures_capped(self):
        """Adaptive with many failures -> capped at MAX_COOLDOWN_HOURS."""
        item = _make_library_item(search_attempts=20, grabs_confirmed=0)
        record = _make_record(air_date=datetime.utcnow() - timedelta(days=3))
        # base 12h, 20 failures -> 12 * 2^8 = 3072, capped to 336
        assert get_effective_cooldown_hours(item, record, "adaptive", None) == MAX_COOLDOWN_HOURS

    def test_adaptive_no_failures(self):
        """Adaptive with no failures -> base hours only."""
        item = _make_library_item(search_attempts=5, grabs_confirmed=5)
        record = _make_record(air_date=datetime.utcnow() - timedelta(days=15))
        # 7-30 days -> base 24h, no failures
        assert get_effective_cooldown_hours(item, record, "adaptive", None) == 24

    def test_adaptive_unknown_date(self):
        """Adaptive with no date info -> 24h default base."""
        assert get_effective_cooldown_hours(None, {}, "adaptive", None) == 24
