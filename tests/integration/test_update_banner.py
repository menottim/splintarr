"""
Integration tests for the update available banner on the dashboard.

Tests verify that the dashboard banner renders correctly based on:
- Update state (newer version available vs. up to date)
- User preference: dismissed_update_version
- User preference: update_check_enabled

The banner HTML is wrapped in ``{% if update_available %}`` so we assert
on the ``<strong>Update Available:</strong>`` markup that only renders
when the conditional is true (the HTML comment above it always renders).
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from splintarr.core.auth import get_current_user_from_cookie
from splintarr.models.user import User

# Sentinel markup that only appears inside the {% if update_available %} block.
BANNER_MARKER = b"<strong>Update Available:</strong>"


@pytest.fixture
def user(db_session: Session) -> User:
    """Create a test user with default update check settings."""
    user = User(
        username="banneruser",
        password_hash="hash",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def authed_client(client: TestClient, user: User) -> TestClient:
    """Create an authenticated test client for dashboard access."""
    from splintarr.main import app

    app.dependency_overrides[get_current_user_from_cookie] = lambda: user
    yield client


MOCK_UPDATE_STATE = {
    "latest_version": "99.0.0",
    "release_url": "https://github.com/menottim/splintarr/releases/tag/v99.0.0",
    "release_name": "v99.0.0 — Future Release",
    "checked_at": "2026-03-03T00:00:00+00:00",
}


class TestUpdateBannerVisibility:
    """Integration tests for the update banner on the dashboard page."""

    def test_banner_shown_when_update_available(self, authed_client: TestClient):
        """Banner appears when a newer version is available and user has not dismissed it."""
        with (
            patch(
                "splintarr.services.update_checker.get_update_state",
                return_value=MOCK_UPDATE_STATE,
            ),
            patch(
                "splintarr.services.update_checker.is_update_available",
                return_value=True,
            ),
        ):
            response = authed_client.get("/dashboard")

        assert response.status_code == 200
        assert BANNER_MARKER in response.content
        assert b"99.0.0" in response.content
        assert b"View release notes" in response.content

    def test_banner_hidden_when_up_to_date(self, authed_client: TestClient):
        """Banner does not appear when the current version matches the latest."""
        same_version_state = {
            "latest_version": "1.1.0",
            "release_url": "https://github.com/menottim/splintarr/releases/tag/v1.1.0",
            "release_name": "v1.1.0",
            "checked_at": "2026-03-03T00:00:00+00:00",
        }
        with (
            patch(
                "splintarr.services.update_checker.get_update_state",
                return_value=same_version_state,
            ),
            patch(
                "splintarr.services.update_checker.is_update_available",
                return_value=False,
            ),
        ):
            response = authed_client.get("/dashboard")

        assert response.status_code == 200
        assert BANNER_MARKER not in response.content

    def test_banner_hidden_when_dismissed(
        self, authed_client: TestClient, user: User
    ):
        """Banner does not appear when user has dismissed the latest version."""
        user.dismissed_update_version = "99.0.0"

        with (
            patch(
                "splintarr.services.update_checker.get_update_state",
                return_value=MOCK_UPDATE_STATE,
            ),
            patch(
                "splintarr.services.update_checker.is_update_available",
                return_value=True,
            ),
        ):
            response = authed_client.get("/dashboard")

        assert response.status_code == 200
        assert BANNER_MARKER not in response.content

    def test_banner_hidden_when_check_disabled(
        self, authed_client: TestClient, user: User
    ):
        """Banner does not appear when user has disabled update checking."""
        user.update_check_enabled = False

        with (
            patch(
                "splintarr.services.update_checker.get_update_state",
                return_value=MOCK_UPDATE_STATE,
            ),
            patch(
                "splintarr.services.update_checker.is_update_available",
                return_value=True,
            ),
        ):
            response = authed_client.get("/dashboard")

        assert response.status_code == 200
        assert BANNER_MARKER not in response.content
