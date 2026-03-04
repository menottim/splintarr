"""
Unit tests for update checker API endpoints.

Tests cover:
- GET /api/updates/status — returns update state and availability
- POST /api/updates/check — triggers a fresh update check
- POST /api/updates/dismiss — sets dismissed_update_version on user
- POST /api/updates/toggle — sets update_check_enabled on user
- Authentication enforcement on all endpoints
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from splintarr.core.auth import get_current_user_from_cookie
from splintarr.models.user import User


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
def mock_db() -> MagicMock:
    """Create a mock DB session for endpoints that write."""
    return MagicMock(spec=Session)


@pytest.fixture
def authed_client(client: TestClient, user: User, mock_db: MagicMock) -> TestClient:
    """Create an authenticated test client with auth and DB dependency overrides."""
    from splintarr.database import get_db
    from splintarr.main import app

    app.dependency_overrides[get_current_user_from_cookie] = lambda: user
    app.dependency_overrides[get_db] = lambda: mock_db
    yield client
    # Restore the original get_db override (from conftest client fixture)
    # The client fixture's teardown calls app.dependency_overrides.clear()


class TestUpdateStatusEndpoint:
    """Tests for GET /api/updates/status."""

    def test_returns_update_state(self, authed_client: TestClient):
        """Status endpoint returns cached update state plus current version."""
        mock_state = {
            "latest_version": "2.0.0",
            "release_url": "https://github.com/menottim/splintarr/releases/tag/v2.0.0",
            "release_name": "v2.0.0",
            "checked_at": "2026-03-03T00:00:00+00:00",
        }
        with patch("splintarr.api.updates.get_update_state", return_value=mock_state), \
             patch("splintarr.api.updates.is_update_available", return_value=True):
            response = authed_client.get("/api/updates/status")

        assert response.status_code == 200
        data = response.json()
        assert data["latest_version"] == "2.0.0"
        assert data["release_url"] == "https://github.com/menottim/splintarr/releases/tag/v2.0.0"
        assert data["release_name"] == "v2.0.0"
        assert data["checked_at"] == "2026-03-03T00:00:00+00:00"
        assert data["current_version"] is not None
        assert data["update_available"] is True
        assert data["check_succeeded"] is True

    def test_no_update_available(self, authed_client: TestClient):
        """Status endpoint returns update_available=False when versions match."""
        mock_state = {
            "latest_version": "1.1.0",
            "release_url": "https://github.com/menottim/splintarr/releases/tag/v1.1.0",
            "release_name": "v1.1.0",
            "checked_at": "2026-03-03T00:00:00+00:00",
        }
        with patch("splintarr.api.updates.get_update_state", return_value=mock_state), \
             patch("splintarr.api.updates.is_update_available", return_value=False):
            response = authed_client.get("/api/updates/status")

        assert response.status_code == 200
        data = response.json()
        assert data["update_available"] is False
        assert data["check_succeeded"] is True

    def test_no_latest_version(self, authed_client: TestClient):
        """Status endpoint handles empty state (no check done yet)."""
        mock_state: dict = {}
        with patch("splintarr.api.updates.get_update_state", return_value=mock_state):
            response = authed_client.get("/api/updates/status")

        assert response.status_code == 200
        data = response.json()
        assert data["update_available"] is False
        assert data["check_succeeded"] is False
        assert "current_version" in data

    def test_requires_auth(self, client: TestClient):
        """Status endpoint requires authentication."""
        response = client.get("/api/updates/status")
        assert response.status_code == 401


class TestCheckNowEndpoint:
    """Tests for POST /api/updates/check."""

    def test_triggers_fresh_check(self, authed_client: TestClient):
        """Check endpoint triggers a fresh update check."""
        mock_state = {
            "latest_version": "2.0.0",
            "release_url": "https://github.com/menottim/splintarr/releases/tag/v2.0.0",
            "release_name": "v2.0.0",
            "checked_at": "2026-03-03T00:00:00+00:00",
        }
        with patch("splintarr.api.updates.check_for_updates", new_callable=AsyncMock,
                    return_value=mock_state), \
             patch("splintarr.api.updates.is_update_available", return_value=True):
            response = authed_client.post("/api/updates/check")

        assert response.status_code == 200
        data = response.json()
        assert data["latest_version"] == "2.0.0"
        assert data["update_available"] is True
        assert data["check_succeeded"] is True

    def test_check_failure_returns_check_succeeded_false(self, authed_client: TestClient):
        """Check endpoint returns check_succeeded=False when GitHub is unreachable."""
        with patch("splintarr.api.updates.check_for_updates", new_callable=AsyncMock,
                    return_value={}):
            response = authed_client.post("/api/updates/check")

        assert response.status_code == 200
        data = response.json()
        assert data["check_succeeded"] is False
        assert data["update_available"] is False

    def test_check_requires_auth(self, client: TestClient):
        """Check endpoint requires authentication."""
        response = client.post("/api/updates/check")
        assert response.status_code == 401


class TestDismissUpdateEndpoint:
    """Tests for POST /api/updates/dismiss."""

    def test_dismiss_sets_version(self, authed_client: TestClient, user, mock_db):
        """Dismiss endpoint sets dismissed_update_version on user."""
        mock_state = {
            "latest_version": "2.0.0",
            "release_url": "https://github.com/menottim/splintarr/releases/tag/v2.0.0",
        }
        with patch("splintarr.api.updates.get_update_state", return_value=mock_state):
            response = authed_client.post("/api/updates/dismiss")

        assert response.status_code == 200
        data = response.json()
        assert data["dismissed"] == "2.0.0"

        # Verify user attribute was set
        assert user.dismissed_update_version == "2.0.0"
        # Verify DB commit was called
        mock_db.commit.assert_called_once()

    def test_dismiss_no_latest(self, authed_client: TestClient, user, mock_db):
        """Dismiss returns null when no latest version is known."""
        mock_state: dict = {}
        with patch("splintarr.api.updates.get_update_state", return_value=mock_state):
            response = authed_client.post("/api/updates/dismiss")

        assert response.status_code == 200
        data = response.json()
        assert data["dismissed"] is None

        # User attribute should not be modified, commit not called
        assert user.dismissed_update_version is None
        mock_db.commit.assert_not_called()

    def test_dismiss_requires_auth(self, client: TestClient):
        """Dismiss endpoint requires authentication."""
        response = client.post("/api/updates/dismiss")
        assert response.status_code == 401


class TestToggleUpdateCheckEndpoint:
    """Tests for POST /api/updates/toggle."""

    def test_toggle_disables(self, authed_client: TestClient, user, mock_db):
        """Toggle disables update checking with explicit body."""
        assert user.update_check_enabled is True

        response = authed_client.post(
            "/api/updates/toggle", json={"enabled": False}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is False
        assert user.update_check_enabled is False
        mock_db.commit.assert_called_once()

    def test_toggle_enables(self, authed_client: TestClient, user, mock_db):
        """Toggle enables update checking with explicit body."""
        user.update_check_enabled = False

        response = authed_client.post(
            "/api/updates/toggle", json={"enabled": True}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is True
        assert user.update_check_enabled is True
        mock_db.commit.assert_called_once()

    def test_toggle_fallback_without_body(self, authed_client: TestClient, user, mock_db):
        """Toggle falls back to inverting when no body provided."""
        assert user.update_check_enabled is True

        response = authed_client.post("/api/updates/toggle")

        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is False
        assert user.update_check_enabled is False

    def test_toggle_requires_auth(self, client: TestClient):
        """Toggle endpoint requires authentication."""
        response = client.post("/api/updates/toggle")
        assert response.status_code == 401
