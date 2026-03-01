"""
Unit tests for Season Pack feature (v0.4.0).

Tests cover:
- SearchQueue model: season_pack_enabled and season_pack_threshold column defaults
- SearchQueueCreate/Update schemas: season pack field validation
- SonarrClient.season_search: correct payload sent to Sonarr API
"""

from unittest.mock import patch

import pytest

from splintarr.models.instance import Instance
from splintarr.models.search_queue import SearchQueue
from splintarr.models.user import User
from splintarr.schemas.search import SearchQueueCreate, SearchQueueResponse, SearchQueueUpdate
from splintarr.services.sonarr import SonarrClient

# ---------------------------------------------------------------------------
# Model defaults
# ---------------------------------------------------------------------------


class TestSeasonPackModelDefaults:
    """Test that SearchQueue model has correct season pack column defaults."""

    def test_season_pack_defaults(self, db_session):
        """Create SearchQueue, verify defaults (enabled=False, threshold=3)."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Sonarr",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        queue = SearchQueue(
            instance_id=instance.id,
            name="Missing Episodes",
            strategy="missing",
        )
        db_session.add(queue)
        db_session.commit()

        assert queue.season_pack_enabled is False
        assert queue.season_pack_threshold == 3

    def test_season_pack_explicit_values(self, db_session):
        """Create SearchQueue with explicit season pack values."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Sonarr",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        queue = SearchQueue(
            instance_id=instance.id,
            name="Season Pack Search",
            strategy="missing",
            season_pack_enabled=True,
            season_pack_threshold=5,
        )
        db_session.add(queue)
        db_session.commit()

        assert queue.season_pack_enabled is True
        assert queue.season_pack_threshold == 5


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestSeasonPackSchemaCreate:
    """Test season pack fields on SearchQueueCreate."""

    def test_create_with_season_pack(self):
        """SearchQueueCreate accepts season_pack fields."""
        schema = SearchQueueCreate(
            instance_id=1,
            name="Season Pack Search",
            strategy="missing",
            season_pack_enabled=True,
            season_pack_threshold=5,
        )

        assert schema.season_pack_enabled is True
        assert schema.season_pack_threshold == 5

    def test_create_defaults(self):
        """SearchQueueCreate defaults: enabled=False, threshold=3."""
        schema = SearchQueueCreate(
            instance_id=1,
            name="Basic Search",
            strategy="missing",
        )

        assert schema.season_pack_enabled is False
        assert schema.season_pack_threshold == 3

    def test_threshold_too_low(self):
        """Threshold < 2 raises ValidationError."""
        with pytest.raises(ValueError):
            SearchQueueCreate(
                instance_id=1,
                name="Bad Search",
                strategy="missing",
                season_pack_threshold=1,
            )

    def test_threshold_too_high(self):
        """Threshold > 50 raises ValidationError."""
        with pytest.raises(ValueError):
            SearchQueueCreate(
                instance_id=1,
                name="Bad Search",
                strategy="missing",
                season_pack_threshold=51,
            )

    def test_threshold_boundary_low(self):
        """Threshold == 2 is valid (minimum)."""
        schema = SearchQueueCreate(
            instance_id=1,
            name="Edge Search",
            strategy="missing",
            season_pack_threshold=2,
        )
        assert schema.season_pack_threshold == 2

    def test_threshold_boundary_high(self):
        """Threshold == 50 is valid (maximum)."""
        schema = SearchQueueCreate(
            instance_id=1,
            name="Edge Search",
            strategy="missing",
            season_pack_threshold=50,
        )
        assert schema.season_pack_threshold == 50


class TestSeasonPackSchemaUpdate:
    """Test season pack fields on SearchQueueUpdate."""

    def test_update_season_pack_fields(self):
        """SearchQueueUpdate accepts optional season pack fields."""
        schema = SearchQueueUpdate(
            season_pack_enabled=True,
            season_pack_threshold=10,
        )

        assert schema.season_pack_enabled is True
        assert schema.season_pack_threshold == 10

    def test_update_defaults_none(self):
        """SearchQueueUpdate defaults both fields to None (not sent)."""
        schema = SearchQueueUpdate()

        assert schema.season_pack_enabled is None
        assert schema.season_pack_threshold is None

    def test_update_threshold_validation(self):
        """SearchQueueUpdate enforces threshold range."""
        with pytest.raises(ValueError):
            SearchQueueUpdate(season_pack_threshold=1)

        with pytest.raises(ValueError):
            SearchQueueUpdate(season_pack_threshold=51)


class TestSeasonPackSchemaResponse:
    """Test season pack fields on SearchQueueResponse."""

    def test_response_includes_season_pack(self):
        """SearchQueueResponse includes season pack fields."""
        from datetime import UTC, datetime

        resp = SearchQueueResponse(
            id=1,
            instance_id=1,
            name="Test Queue",
            strategy="missing",
            recurring=False,
            is_active=True,
            status="pending",
            consecutive_failures=0,
            created_at=datetime.now(UTC),
            season_pack_enabled=True,
            season_pack_threshold=7,
        )

        assert resp.season_pack_enabled is True
        assert resp.season_pack_threshold == 7

    def test_response_defaults(self):
        """SearchQueueResponse defaults: enabled=False, threshold=3."""
        from datetime import UTC, datetime

        resp = SearchQueueResponse(
            id=1,
            instance_id=1,
            name="Test Queue",
            strategy="missing",
            recurring=False,
            is_active=True,
            status="pending",
            consecutive_failures=0,
            created_at=datetime.now(UTC),
        )

        assert resp.season_pack_enabled is False
        assert resp.season_pack_threshold == 3


# ---------------------------------------------------------------------------
# SonarrClient.season_search
# ---------------------------------------------------------------------------


class TestSeasonSearchCommand:
    """Test SonarrClient.season_search method."""

    @pytest.mark.asyncio
    async def test_season_search_command(self):
        """season_search posts correct payload to Sonarr API."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        expected_response = {
            "id": 99999,
            "name": "SeasonSearch",
            "status": "queued",
        }

        with patch.object(client, "_request") as mock_request:
            mock_request.return_value = expected_response

            result = await client.season_search(series_id=42, season_number=3)

            assert result == expected_response
            mock_request.assert_called_once_with(
                "POST",
                "/api/v3/command",
                json={
                    "name": "SeasonSearch",
                    "seriesId": 42,
                    "seasonNumber": 3,
                },
            )

    @pytest.mark.asyncio
    async def test_season_search_different_params(self):
        """season_search correctly passes varied series/season IDs."""
        client = SonarrClient(
            url="https://sonarr.example.com",
            api_key="a" * 32,
        )

        with patch.object(client, "_request") as mock_request:
            mock_request.return_value = {"id": 1, "name": "SeasonSearch", "status": "queued"}

            await client.season_search(series_id=100, season_number=1)

            mock_request.assert_called_once_with(
                "POST",
                "/api/v3/command",
                json={
                    "name": "SeasonSearch",
                    "seriesId": 100,
                    "seasonNumber": 1,
                },
            )
