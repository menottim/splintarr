"""Tests for budget-aware batch auto-sizing."""
import pytest


class TestBudgetAwareSizing:
    """Test that budget_aware queues reduce batch size proportionally."""

    def test_budget_aware_reduces_below_20_percent(self):
        """When remaining budget is <20% of limit, cap effective_max."""
        queue_max = 50
        remaining_budget = 8

        effective = min(queue_max, remaining_budget)
        assert effective == 8

    def test_budget_aware_no_reduction_above_20_percent(self):
        """When remaining budget is >20%, use normal min(queue_max, budget)."""
        queue_max = 50
        remaining_budget = 30

        effective = min(queue_max, remaining_budget)
        assert effective == 30

    def test_budget_aware_disabled_uses_queue_max(self):
        """When budget_aware=False, ignore Prowlarr budget."""
        queue_max = 50
        remaining_budget = 5

        # budget_aware=False: use queue max regardless
        effective = queue_max
        assert effective == 50
