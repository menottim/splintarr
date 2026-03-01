"""
Unit tests for the scoring engine (splintarr.services.scoring).

Tests all three factor calculators (recency, attempts, staleness),
the strategy-weighted composite score, reason strings, and edge cases.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from splintarr.services.scoring import (
    _attempts_score,
    _recency_score,
    _staleness_score,
    compute_score,
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
    search_attempts: int = 0,
    last_searched_at: datetime | None = None,
    grabs_confirmed: int = 0,
) -> MagicMock:
    """Build a mock LibraryItem with scoring-relevant attributes."""
    item = MagicMock()
    item.search_attempts = search_attempts
    item.last_searched_at = last_searched_at
    item.grabs_confirmed = grabs_confirmed
    return item


# ===================================================================
# Recency factor tests
# ===================================================================
class TestRecencyScore:
    """Tests for _recency_score factor calculator."""

    def test_recency_within_24h(self):
        """Content aired less than 24 hours ago gets max recency score."""
        record = _make_record(air_date=datetime.utcnow() - timedelta(hours=12))
        assert _recency_score(record) == 40

    def test_recency_within_7d(self):
        """Content aired 1-7 days ago gets 30."""
        record = _make_record(air_date=datetime.utcnow() - timedelta(days=3))
        assert _recency_score(record) == 30

    def test_recency_within_30d(self):
        """Content aired 7-30 days ago gets 20."""
        record = _make_record(air_date=datetime.utcnow() - timedelta(days=15))
        assert _recency_score(record) == 20

    def test_recency_within_1y(self):
        """Content aired 30 days to 1 year ago gets 10."""
        record = _make_record(air_date=datetime.utcnow() - timedelta(days=180))
        assert _recency_score(record) == 10

    def test_recency_over_1y(self):
        """Content aired more than 1 year ago gets 5."""
        record = _make_record(air_date=datetime.utcnow() - timedelta(days=400))
        assert _recency_score(record) == 5

    def test_recency_unknown_date(self):
        """Record with no date fields gets middle-ground score of 15."""
        record: dict = {}
        assert _recency_score(record) == 15

    def test_recency_invalid_date(self):
        """Record with unparseable date gets middle-ground score of 15."""
        record = {"airDateUtc": "not-a-date"}
        assert _recency_score(record) == 15

    def test_recency_falls_back_to_added(self):
        """Uses 'added' field when 'airDateUtc' is absent (Radarr)."""
        record = _make_record(added=datetime.utcnow() - timedelta(hours=6))
        assert _recency_score(record) == 40

    def test_recency_prefers_airDateUtc(self):
        """Uses 'airDateUtc' over 'added' when both are present."""
        record = _make_record(
            air_date=datetime.utcnow() - timedelta(days=400),  # > 1 year → 5
            added=datetime.utcnow() - timedelta(hours=6),  # < 24h → 40
        )
        assert _recency_score(record) == 5

    def test_recency_none_airDateUtc(self):
        """Explicit None for airDateUtc falls back to added."""
        record = {
            "airDateUtc": None,
            "added": (datetime.utcnow() - timedelta(days=2)).isoformat() + "Z",
        }
        assert _recency_score(record) == 30


# ===================================================================
# Attempts factor tests
# ===================================================================
class TestAttemptsScore:
    """Tests for _attempts_score factor calculator."""

    def test_attempts_zero(self):
        """Never searched item gets max attempts score."""
        item = _make_library_item(search_attempts=0)
        assert _attempts_score(item) == 30

    def test_attempts_few(self):
        """1-5 attempts gets 25."""
        item = _make_library_item(search_attempts=3)
        assert _attempts_score(item) == 25

    def test_attempts_moderate(self):
        """6-10 attempts gets 15."""
        item = _make_library_item(search_attempts=8)
        assert _attempts_score(item) == 15

    def test_attempts_high(self):
        """11-20 attempts gets 8."""
        item = _make_library_item(search_attempts=15)
        assert _attempts_score(item) == 8

    def test_attempts_many(self):
        """20+ attempts gets minimum score of 2."""
        item = _make_library_item(search_attempts=50)
        assert _attempts_score(item) == 2

    def test_attempts_none_library_item(self):
        """None library_item treated as never searched → 30."""
        assert _attempts_score(None) == 30

    def test_attempts_boundary_5(self):
        """Exactly 5 attempts is in 1-5 range → 25."""
        item = _make_library_item(search_attempts=5)
        assert _attempts_score(item) == 25

    def test_attempts_boundary_6(self):
        """Exactly 6 attempts is in 6-10 range → 15."""
        item = _make_library_item(search_attempts=6)
        assert _attempts_score(item) == 15

    def test_attempts_boundary_10(self):
        """Exactly 10 attempts is in 6-10 range → 15."""
        item = _make_library_item(search_attempts=10)
        assert _attempts_score(item) == 15

    def test_attempts_boundary_11(self):
        """Exactly 11 attempts is in 11-20 range → 8."""
        item = _make_library_item(search_attempts=11)
        assert _attempts_score(item) == 8

    def test_attempts_boundary_20(self):
        """Exactly 20 attempts is in 11-20 range → 8."""
        item = _make_library_item(search_attempts=20)
        assert _attempts_score(item) == 8

    def test_attempts_boundary_21(self):
        """Exactly 21 attempts is in 20+ range → 2."""
        item = _make_library_item(search_attempts=21)
        assert _attempts_score(item) == 2


# ===================================================================
# Staleness factor tests
# ===================================================================
class TestStalenessScore:
    """Tests for _staleness_score factor calculator."""

    def test_staleness_never(self):
        """Never-searched item gets max staleness score."""
        item = _make_library_item(last_searched_at=None)
        assert _staleness_score(item) == 30

    def test_staleness_over_7d(self):
        """Last searched more than 7 days ago gets 25."""
        item = _make_library_item(
            last_searched_at=datetime.utcnow() - timedelta(days=10),
        )
        assert _staleness_score(item) == 25

    def test_staleness_over_3d(self):
        """Last searched 3-7 days ago gets 20."""
        item = _make_library_item(
            last_searched_at=datetime.utcnow() - timedelta(days=5),
        )
        assert _staleness_score(item) == 20

    def test_staleness_over_1d(self):
        """Last searched 1-3 days ago gets 15."""
        item = _make_library_item(
            last_searched_at=datetime.utcnow() - timedelta(days=2),
        )
        assert _staleness_score(item) == 15

    def test_staleness_recent(self):
        """Last searched less than 1 day ago gets 5."""
        item = _make_library_item(
            last_searched_at=datetime.utcnow() - timedelta(hours=6),
        )
        assert _staleness_score(item) == 5

    def test_staleness_none_library_item(self):
        """None library_item treated as never searched → 30."""
        assert _staleness_score(None) == 30


# ===================================================================
# Composite compute_score tests
# ===================================================================
class TestComputeScore:
    """Tests for the main compute_score function."""

    def test_compute_score_missing_favors_recency(self):
        """With 'missing' strategy, a fresh item scores higher than an old one."""
        fresh_record = _make_record(air_date=datetime.utcnow() - timedelta(hours=6))
        old_record = _make_record(air_date=datetime.utcnow() - timedelta(days=400))

        fresh_score, _ = compute_score(fresh_record, None, "missing")
        old_score, _ = compute_score(old_record, None, "missing")

        assert fresh_score > old_score

    def test_compute_score_cutoff_favors_staleness(self):
        """With 'cutoff_unmet' strategy, stale item scores higher than fresh-searched."""
        stale_item = _make_library_item(
            search_attempts=3,
            last_searched_at=datetime.utcnow() - timedelta(days=10),
        )
        fresh_item = _make_library_item(
            search_attempts=3,
            last_searched_at=datetime.utcnow() - timedelta(hours=2),
        )

        record = _make_record(air_date=datetime.utcnow() - timedelta(days=60))

        stale_score, _ = compute_score(record, stale_item, "cutoff_unmet")
        fresh_score, _ = compute_score(record, fresh_item, "cutoff_unmet")

        assert stale_score > fresh_score

    def test_compute_score_returns_reason_string(self):
        """Reason is always a non-empty string."""
        record = _make_record(air_date=datetime.utcnow() - timedelta(hours=6))
        _, reason = compute_score(record, None, "missing")

        assert isinstance(reason, str)
        assert len(reason) > 0

    def test_compute_score_no_library_item(self):
        """None library_item produces sensible defaults (high score for never-searched)."""
        record = _make_record(air_date=datetime.utcnow() - timedelta(hours=12))
        score, reason = compute_score(record, None, "missing")

        # With no library item: attempts=30, staleness=30, recency=40
        # All maxed out → should be close to 100
        assert score >= 80.0
        assert isinstance(reason, str)

    def test_score_always_0_to_100(self):
        """Score is always within [0, 100] for a variety of inputs."""
        test_cases = [
            # (record, library_item, strategy)
            ({}, None, "missing"),
            (_make_record(air_date=datetime.utcnow()), None, "recent"),
            (
                _make_record(air_date=datetime.utcnow() - timedelta(days=1000)),
                _make_library_item(search_attempts=100, last_searched_at=datetime.utcnow()),
                "cutoff_unmet",
            ),
            ({"airDateUtc": "garbage"}, _make_library_item(), "missing"),
            ({}, _make_library_item(search_attempts=0, last_searched_at=None), "recent"),
            (
                _make_record(air_date=datetime.utcnow() - timedelta(hours=1)),
                _make_library_item(
                    search_attempts=50,
                    last_searched_at=datetime.utcnow() - timedelta(days=30),
                ),
                "unknown_strategy",
            ),
        ]

        for record, item, strategy in test_cases:
            score, reason = compute_score(record, item, strategy)
            assert 0.0 <= score <= 100.0, f"Score {score} out of range for {strategy}"
            assert isinstance(reason, str)

    def test_compute_score_recent_strategy_weights(self):
        """'recent' strategy heavily favors recency over other factors."""
        # Fresh content, but heavily searched recently
        fresh_record = _make_record(air_date=datetime.utcnow() - timedelta(hours=3))
        searched_item = _make_library_item(
            search_attempts=15,
            last_searched_at=datetime.utcnow() - timedelta(hours=2),
        )

        # Old content, never searched
        old_record = _make_record(air_date=datetime.utcnow() - timedelta(days=400))
        unsearched_item = _make_library_item(
            search_attempts=0,
            last_searched_at=None,
        )

        fresh_score, _ = compute_score(fresh_record, searched_item, "recent")
        old_score, _ = compute_score(old_record, unsearched_item, "recent")

        # With "recent" strategy (recency=2.0, attempts=0.5, staleness=0.5):
        # Fresh: recency=40*2.0=80, attempts=8*0.5=4, staleness=5*0.5=2.5 → 86.5
        # Old: recency=5*2.0=10, attempts=30*0.5=15, staleness=30*0.5=15 → 40
        assert fresh_score > old_score

    def test_compute_score_unknown_strategy_uses_defaults(self):
        """Unknown strategy name falls back to equal weights."""
        record = _make_record(air_date=datetime.utcnow() - timedelta(days=3))
        item = _make_library_item(
            search_attempts=2, last_searched_at=datetime.utcnow() - timedelta(days=5)
        )

        score, reason = compute_score(record, item, "some_unknown_strategy")
        assert 0.0 <= score <= 100.0
        assert isinstance(reason, str)

    def test_compute_score_score_is_rounded(self):
        """Score is rounded to 1 decimal place."""
        record = _make_record(air_date=datetime.utcnow() - timedelta(days=3))
        item = _make_library_item(
            search_attempts=2, last_searched_at=datetime.utcnow() - timedelta(days=5)
        )

        score, _ = compute_score(record, item, "missing")

        # Check it's rounded to 1 decimal
        assert score == round(score, 1)


# ===================================================================
# Reason string tests
# ===================================================================
class TestReasonStrings:
    """Tests for reason string generation."""

    def test_reason_recently_aired(self):
        """Fresh content with 'missing' strategy → 'recently aired'."""
        record = _make_record(air_date=datetime.utcnow() - timedelta(hours=6))
        _, reason = compute_score(record, None, "missing")
        assert reason == "recently aired"

    def test_reason_older_content(self):
        """Old content with 'recent' strategy → 'older content'."""
        record = _make_record(air_date=datetime.utcnow() - timedelta(days=500))
        # With "recent" strategy, recency weight is 2.0
        # recency_raw=5, weighted=10; attempts=30*0.5=15; staleness=30*0.5=15
        # attempts or staleness will dominate, not recency
        # Need to make attempts and staleness low so recency dominates
        item = _make_library_item(
            search_attempts=50,  # → 2 raw
            last_searched_at=datetime.utcnow() - timedelta(hours=2),  # → 5 raw
        )
        # recency=5*2.0=10, attempts=2*0.5=1, staleness=5*0.5=2.5
        # recency dominates and raw score <= 10, so "older content"
        _, reason = compute_score(record, item, "recent")
        assert reason == "older content"

    def test_reason_never_searched(self):
        """Never-searched item with dominant attempts factor → 'never searched'."""
        # Use cutoff_unmet: attempts weight=0.8
        # Make recency low so attempts dominates
        record = _make_record(air_date=datetime.utcnow() - timedelta(days=60))
        item = _make_library_item(
            search_attempts=0,
            last_searched_at=datetime.utcnow() - timedelta(hours=6),  # staleness=5, weighted=7.5
        )
        # recency=10*0.7=7, attempts=30*0.8=24, staleness=5*1.5=7.5
        # attempts dominates at 24
        _, reason = compute_score(record, item, "cutoff_unmet")
        assert reason == "never searched"

    def test_reason_searched_many_times(self):
        """Heavily searched item → 'searched Nx, low results'."""
        # With default (equal) weights, we need attempts to dominate:
        # recency=5 (>1yr) → 5*1=5, staleness=5 (<1day) → 5*1=5
        # attempts=8 (15 searches, 11-20 range) → 8*1=8, dominates!
        record = _make_record(air_date=datetime.utcnow() - timedelta(days=400))
        item = _make_library_item(
            search_attempts=15,
            last_searched_at=datetime.utcnow() - timedelta(hours=6),
        )
        _, reason = compute_score(record, item, "default_equal_weights")
        assert reason == "searched 15x, low results"

    def test_reason_not_searched_recently(self):
        """Stale item with 'cutoff_unmet' strategy → 'not searched recently'."""
        record = _make_record(air_date=datetime.utcnow() - timedelta(days=60))
        item = _make_library_item(
            search_attempts=8,  # → 15 raw
            last_searched_at=datetime.utcnow() - timedelta(days=10),  # → 25 raw
        )
        # cutoff_unmet: recency=10*0.7=7, attempts=15*0.8=12, staleness=25*1.5=37.5
        # staleness dominates
        _, reason = compute_score(record, item, "cutoff_unmet")
        assert reason == "not searched recently"
