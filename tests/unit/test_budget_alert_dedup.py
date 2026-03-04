"""Tests for budget alert dedup logic."""
import pytest

from splintarr.api.dashboard import _check_budget_alerts, _alerted_indexers


class TestBudgetAlertDedup:
    """Test that budget alerts fire once per indexer per period."""

    def setup_method(self):
        _alerted_indexers.clear()

    def test_alert_fires_on_first_high_usage(self):
        alerts = _check_budget_alerts([
            {"name": "NZBgeek", "query_limit": 100, "queries_used": 85, "limits_unit": "day"},
        ])
        assert len(alerts) == 1
        assert alerts[0]["indexer_name"] == "NZBgeek"

    def test_alert_does_not_repeat(self):
        _check_budget_alerts([
            {"name": "NZBgeek", "query_limit": 100, "queries_used": 85, "limits_unit": "day"},
        ])
        alerts = _check_budget_alerts([
            {"name": "NZBgeek", "query_limit": 100, "queries_used": 90, "limits_unit": "day"},
        ])
        assert len(alerts) == 0

    def test_no_alert_below_threshold(self):
        alerts = _check_budget_alerts([
            {"name": "NZBgeek", "query_limit": 100, "queries_used": 50, "limits_unit": "day"},
        ])
        assert len(alerts) == 0

    def test_no_alert_without_limit(self):
        alerts = _check_budget_alerts([
            {"name": "NZBgeek", "query_limit": None, "queries_used": 500, "limits_unit": "day"},
        ])
        assert len(alerts) == 0
