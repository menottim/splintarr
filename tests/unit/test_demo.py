"""
Unit tests for demo mode service.

Tests verify:
- Demo mode detection (is_demo_active)
- Synthetic data generator shapes match real API responses
- Simulation lifecycle (start/stop)
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm import Session

from splintarr.models.instance import Instance
from splintarr.models.search_queue import SearchQueue
from splintarr.models.user import User
from splintarr.services.demo import (
    get_demo_activity,
    get_demo_indexer_health,
    get_demo_library_stats,
    get_demo_stats,
    get_demo_system_status,
    is_demo_active,
    start_simulation,
    stop_simulation,
)


@pytest.fixture
def user(db_session: Session) -> User:
    """Create a test user."""
    user = User(
        username="testuser",
        password_hash="hash",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def instance(db_session: Session, user: User) -> Instance:
    """Create a test instance for the user."""
    inst = Instance(
        user_id=user.id,
        name="Test Sonarr",
        instance_type="sonarr",
        url="https://sonarr.example.com",
        api_key="encrypted-key",
        is_active=True,
    )
    db_session.add(inst)
    db_session.commit()
    db_session.refresh(inst)
    return inst


@pytest.fixture
def queue(db_session: Session, instance: Instance) -> SearchQueue:
    """Create a test search queue."""
    queue = SearchQueue(
        instance_id=instance.id,
        name="Test Queue",
        strategy="missing",
        status="pending",
        is_active=True,
    )
    db_session.add(queue)
    db_session.commit()
    db_session.refresh(queue)
    return queue


# ---------------------------------------------------------------------------
# is_demo_active tests
# ---------------------------------------------------------------------------


class TestIsDemoActive:
    """Verify demo mode detection based on onboarding state."""

    def test_demo_active_fresh_user(self, db_session: Session, user: User):
        """Fresh user with no instances or queues -> demo active."""
        assert is_demo_active(db_session, user.id) is True

    def test_demo_active_with_instance_only(
        self, db_session: Session, user: User, instance: Instance
    ):
        """User with instance but no queue -> demo still active."""
        assert is_demo_active(db_session, user.id) is True

    def test_demo_inactive_with_instance_and_queue(
        self, db_session: Session, user: User, instance: Instance, queue: SearchQueue
    ):
        """User with both instance and queue -> demo inactive."""
        assert is_demo_active(db_session, user.id) is False


# ---------------------------------------------------------------------------
# Data shape tests
# ---------------------------------------------------------------------------


class TestDemoStats:
    """Verify get_demo_stats matches /api/dashboard/stats shape."""

    def test_shape(self):
        stats = get_demo_stats()
        assert "instances" in stats
        assert "search_queues" in stats
        assert "searches" in stats
        assert stats["demo"] is True

        # Nested keys
        assert "total" in stats["instances"]
        assert "active" in stats["instances"]
        assert "inactive" in stats["instances"]
        assert "total" in stats["search_queues"]
        assert "active" in stats["search_queues"]
        assert "paused" in stats["search_queues"]
        assert "today" in stats["searches"]
        assert "this_week" in stats["searches"]
        assert "success_rate" in stats["searches"]
        assert "grab_rate" in stats["searches"]

    def test_values_are_numeric(self):
        stats = get_demo_stats()
        assert isinstance(stats["instances"]["total"], int)
        assert isinstance(stats["searches"]["success_rate"], float)


class TestDemoActivity:
    """Verify get_demo_activity matches /api/dashboard/activity shape."""

    def test_shape(self):
        data = get_demo_activity()
        assert "activity" in data
        assert data["demo"] is True
        assert len(data["activity"]) == 5

    def test_item_keys(self):
        data = get_demo_activity()
        required_keys = {
            "id", "instance_name", "strategy", "status",
            "items_searched", "items_found", "searches_triggered",
            "started_at", "completed_at", "search_queue_id", "search_name",
        }
        for item in data["activity"]:
            assert required_keys.issubset(item.keys())

    def test_timestamps_are_iso_strings(self):
        data = get_demo_activity()
        for item in data["activity"]:
            assert isinstance(item["started_at"], str)
            assert "T" in item["started_at"]  # ISO format check


class TestDemoSystemStatus:
    """Verify get_demo_system_status matches /api/dashboard/system-status shape."""

    def test_shape(self):
        data = get_demo_system_status()
        assert "instances" in data
        assert "integrations" in data
        assert "services" in data
        assert data["demo"] is True

    def test_instance_keys(self):
        data = get_demo_system_status()
        inst = data["instances"][0]
        required_keys = {
            "id", "name", "instance_type", "url", "connection_status",
            "last_connection_test", "consecutive_failures",
            "response_time_ms", "connection_error",
        }
        assert required_keys.issubset(inst.keys())

    def test_integrations(self):
        data = get_demo_system_status()
        assert "discord" in data["integrations"]
        assert "prowlarr" in data["integrations"]
        assert "configured" in data["integrations"]["discord"]
        assert "active" in data["integrations"]["discord"]

    def test_services(self):
        data = get_demo_system_status()
        assert "database" in data["services"]
        assert "scheduler" in data["services"]
        assert data["services"]["database"]["status"] == "healthy"


class TestDemoLibraryStats:
    """Verify get_demo_library_stats matches /api/library/stats shape."""

    def test_shape(self):
        stats = get_demo_library_stats()
        required_keys = {
            "total_items", "complete_count", "missing_count",
            "series_count", "movie_count", "cutoff_unmet_count",
        }
        assert required_keys.issubset(stats.keys())
        assert stats["demo"] is True

    def test_counts_are_consistent(self):
        stats = get_demo_library_stats()
        assert stats["complete_count"] + stats["missing_count"] == stats["total_items"]
        assert stats["series_count"] + stats["movie_count"] == stats["total_items"]


class TestDemoIndexerHealth:
    """Verify get_demo_indexer_health matches /api/dashboard/indexer-health shape."""

    def test_shape(self):
        data = get_demo_indexer_health()
        assert data["configured"] is True
        assert "indexers" in data
        assert data["demo"] is True
        assert len(data["indexers"]) == 4

    def test_indexer_keys(self):
        data = get_demo_indexer_health()
        required_keys = {"name", "query_limit", "queries_used", "limits_unit", "is_disabled"}
        for idx in data["indexers"]:
            assert required_keys.issubset(idx.keys())

    def test_has_disabled_indexer(self):
        data = get_demo_indexer_health()
        disabled = [i for i in data["indexers"] if i["is_disabled"]]
        assert len(disabled) >= 1


# ---------------------------------------------------------------------------
# Simulation lifecycle tests
# ---------------------------------------------------------------------------


class TestSimulationLifecycle:
    """Verify simulation start/stop behavior."""

    @pytest.mark.asyncio
    async def test_start_and_stop(self, db_session: Session, user: User):
        """Simulation starts and stops cleanly."""
        from sqlalchemy.orm import sessionmaker

        factory = sessionmaker(bind=db_session.get_bind())

        with patch("splintarr.services.demo._run_simulation_cycle", new_callable=AsyncMock):
            start_simulation(factory)

            # Give the task time to start
            await asyncio.sleep(0.1)

            await stop_simulation()

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self):
        """Stopping when no simulation is running should be a no-op."""
        await stop_simulation()  # Should not raise
