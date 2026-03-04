"""Integration tests for indexer budget visibility feature."""
import pytest

from splintarr.api.dashboard import _check_budget_alerts, _alerted_indexers


class TestBudgetAlertIntegration:
    """Test budget alerts fire correctly from indexer health data."""

    def setup_method(self):
        _alerted_indexers.clear()

    def test_multiple_indexers_only_high_ones_alert(self):
        alerts = _check_budget_alerts([
            {"name": "NZBgeek", "query_limit": 100, "queries_used": 85, "limits_unit": "day"},
            {"name": "DogNZB", "query_limit": 50, "queries_used": 10, "limits_unit": "day"},
            {"name": "NZBFinder", "query_limit": 200, "queries_used": 180, "limits_unit": "day"},
        ])
        assert len(alerts) == 2
        names = [a["indexer_name"] for a in alerts]
        assert "NZBgeek" in names
        assert "NZBFinder" in names
        assert "DogNZB" not in names

    def test_different_units_tracked_separately(self):
        _check_budget_alerts([
            {"name": "NZBgeek", "query_limit": 100, "queries_used": 85, "limits_unit": "day"},
        ])
        # Same indexer but hourly limit — should alert separately
        alerts = _check_budget_alerts([
            {"name": "NZBgeek", "query_limit": 10, "queries_used": 9, "limits_unit": "hour"},
        ])
        assert len(alerts) == 1

    def test_exact_threshold_triggers_alert(self):
        alerts = _check_budget_alerts([
            {"name": "NZBgeek", "query_limit": 100, "queries_used": 80, "limits_unit": "day"},
        ])
        assert len(alerts) == 1

    def test_zero_limit_treated_as_no_limit(self):
        alerts = _check_budget_alerts([
            {"name": "NZBgeek", "query_limit": 0, "queries_used": 50, "limits_unit": "day"},
        ])
        assert len(alerts) == 0
