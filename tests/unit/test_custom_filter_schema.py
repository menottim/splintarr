"""Tests for CustomFilterConfig and custom strategy schema validation."""

import pytest
from pydantic import ValidationError

from splintarr.schemas.search import CustomFilterConfig, SearchQueueCreate, SearchQueueUpdate

# ---------------------------------------------------------------------------
# CustomFilterConfig standalone tests
# ---------------------------------------------------------------------------


class TestCustomFilterConfig:
    """Tests for the CustomFilterConfig Pydantic model."""

    def test_minimal_valid_config(self):
        """CustomFilterConfig with only required field (sources) should be accepted."""
        config = CustomFilterConfig(sources=["missing"])
        assert config.sources == ["missing"]
        assert config.year_min is None
        assert config.year_max is None
        assert config.quality_profiles == []
        assert config.statuses == []

    def test_full_valid_config(self):
        """CustomFilterConfig with all fields populated should be accepted."""
        config = CustomFilterConfig(
            sources=["missing", "cutoff_unmet"],
            year_min=2000,
            year_max=2025,
            quality_profiles=["HD-1080p", "Ultra-HD"],
            statuses=["continuing", "ended"],
        )
        assert config.sources == ["missing", "cutoff_unmet"]
        assert config.year_min == 2000
        assert config.year_max == 2025
        assert config.quality_profiles == ["HD-1080p", "Ultra-HD"]
        assert config.statuses == ["continuing", "ended"]

    def test_empty_sources_rejected(self):
        """Empty sources list should be rejected (min_length=1)."""
        with pytest.raises(ValidationError, match="sources"):
            CustomFilterConfig(sources=[])

    def test_invalid_source_name_rejected(self):
        """Invalid source name should be rejected by the Literal constraint."""
        with pytest.raises(ValidationError, match="sources"):
            CustomFilterConfig(sources=["invalid_source"])

    def test_invalid_status_name_rejected(self):
        """Invalid status name should be rejected by the Literal constraint."""
        with pytest.raises(ValidationError, match="statuses"):
            CustomFilterConfig(sources=["missing"], statuses=["invalid_status"])

    def test_year_min_greater_than_year_max_rejected(self):
        """year_min > year_max should be rejected by the model validator."""
        with pytest.raises(ValidationError, match="year_min must be <= year_max"):
            CustomFilterConfig(sources=["missing"], year_min=2025, year_max=2000)

    def test_year_min_equals_year_max_accepted(self):
        """year_min == year_max should be accepted (single-year filter)."""
        config = CustomFilterConfig(sources=["missing"], year_min=2020, year_max=2020)
        assert config.year_min == 2020
        assert config.year_max == 2020

    def test_year_min_only_accepted(self):
        """year_min without year_max should be accepted."""
        config = CustomFilterConfig(sources=["missing"], year_min=2000)
        assert config.year_min == 2000
        assert config.year_max is None

    def test_year_max_only_accepted(self):
        """year_max without year_min should be accepted."""
        config = CustomFilterConfig(sources=["missing"], year_max=2025)
        assert config.year_min is None
        assert config.year_max == 2025

    def test_all_valid_statuses(self):
        """All four valid status values should be accepted."""
        config = CustomFilterConfig(
            sources=["missing"],
            statuses=["continuing", "ended", "upcoming", "deleted"],
        )
        assert len(config.statuses) == 4

    def test_year_out_of_range_rejected(self):
        """Year values outside 1900-2100 should be rejected."""
        with pytest.raises(ValidationError):
            CustomFilterConfig(sources=["missing"], year_min=1899)
        with pytest.raises(ValidationError):
            CustomFilterConfig(sources=["missing"], year_max=2101)


# ---------------------------------------------------------------------------
# SearchQueueCreate cross-validation tests
# ---------------------------------------------------------------------------


class TestSearchQueueCreateCustomStrategy:
    """Tests for custom strategy validation in SearchQueueCreate."""

    def _base_data(self, **overrides):
        """Return minimal valid SearchQueueCreate data, with optional overrides."""
        data = {
            "instance_id": 1,
            "name": "Test Search",
            "strategy": "missing",
            "filters": None,
        }
        data.update(overrides)
        return data

    def test_custom_strategy_with_valid_filters_accepted(self):
        """strategy='custom' with a valid CustomFilterConfig should be accepted."""
        queue = SearchQueueCreate(
            **self._base_data(
                strategy="custom",
                filters={"sources": ["missing"]},
            )
        )
        assert queue.strategy == "custom"
        assert isinstance(queue.filters, CustomFilterConfig)
        assert queue.filters.sources == ["missing"]

    def test_custom_strategy_without_filters_rejected(self):
        """strategy='custom' with filters=None should be rejected."""
        with pytest.raises(ValidationError, match="Custom strategy requires filters"):
            SearchQueueCreate(**self._base_data(strategy="custom", filters=None))

    def test_non_custom_strategy_with_filters_rejected(self):
        """strategy='missing' with filters should be rejected."""
        with pytest.raises(ValidationError, match="Filters only allowed with custom strategy"):
            SearchQueueCreate(
                **self._base_data(
                    strategy="missing",
                    filters={"sources": ["missing"]},
                )
            )

    def test_non_custom_strategy_without_filters_accepted(self):
        """strategy='missing' with filters=None should be accepted (normal case)."""
        queue = SearchQueueCreate(**self._base_data(strategy="missing", filters=None))
        assert queue.strategy == "missing"
        assert queue.filters is None

    def test_custom_strategy_with_full_filters_accepted(self):
        """strategy='custom' with a fully-populated filter config should work."""
        queue = SearchQueueCreate(
            **self._base_data(
                strategy="custom",
                filters={
                    "sources": ["missing", "cutoff_unmet"],
                    "year_min": 2000,
                    "year_max": 2025,
                    "quality_profiles": ["HD-1080p"],
                    "statuses": ["continuing", "ended"],
                },
            )
        )
        assert queue.filters is not None
        assert queue.filters.year_min == 2000


# ---------------------------------------------------------------------------
# SearchQueueUpdate cross-validation tests (partial update semantics)
# ---------------------------------------------------------------------------


class TestSearchQueueUpdateCustomStrategy:
    """Tests for custom strategy validation in SearchQueueUpdate.

    The update validator is lenient: it only enforces the constraint when
    both strategy and filters are explicitly provided together.
    """

    def test_update_with_neither_strategy_nor_filters(self):
        """Partial update with no strategy or filters should be accepted."""
        update = SearchQueueUpdate(name="New Name")
        assert update.strategy is None
        assert update.filters is None

    def test_update_with_strategy_only(self):
        """Partial update setting only strategy (no filters) should be accepted."""
        update = SearchQueueUpdate(strategy="custom")
        assert update.strategy == "custom"
        assert update.filters is None

    def test_update_with_filters_only(self):
        """Partial update setting only filters (no strategy) should be accepted."""
        update = SearchQueueUpdate(filters={"sources": ["missing"]})
        assert isinstance(update.filters, CustomFilterConfig)
        assert update.strategy is None

    def test_update_custom_strategy_with_filters_accepted(self):
        """Update with strategy='custom' + filters should be accepted."""
        update = SearchQueueUpdate(
            strategy="custom",
            filters={"sources": ["cutoff_unmet"]},
        )
        assert update.strategy == "custom"
        assert update.filters is not None

    def test_update_non_custom_strategy_with_filters_rejected(self):
        """Update with strategy='missing' + filters should be rejected."""
        with pytest.raises(ValidationError, match="Filters only allowed with custom strategy"):
            SearchQueueUpdate(
                strategy="missing",
                filters={"sources": ["missing"]},
            )
