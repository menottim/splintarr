"""
Unit tests for config export and integrity check endpoints.

Tests verify:
1. Export includes instances with redacted API keys
2. Export includes version and exported_at
3. Integrity check returns "ok" status
"""

import pytest
from sqlalchemy.orm import Session

from splintarr.core.auth import create_access_token
from splintarr.models.instance import Instance
from splintarr.models.notification import NotificationConfig
from splintarr.models.user import User


@pytest.fixture
def user(db_session: Session) -> User:
    """Create a test user."""
    user = User(
        username="exportuser",
        password_hash="hash",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def instance(db_session: Session, user: User) -> Instance:
    """Create a test instance with an API key."""
    inst = Instance(
        user_id=user.id,
        name="Test Sonarr",
        instance_type="sonarr",
        url="https://sonarr.example.com",
        api_key="super-secret-api-key",
        is_active=True,
    )
    db_session.add(inst)
    db_session.commit()
    db_session.refresh(inst)
    return inst


@pytest.fixture
def notification_config(db_session: Session, user: User) -> NotificationConfig:
    """Create a test notification config."""
    config = NotificationConfig(
        user_id=user.id,
        webhook_url="encrypted-webhook-url",
        events_enabled='{"search_triggered": true}',
        is_active=True,
    )
    db_session.add(config)
    db_session.commit()
    db_session.refresh(config)
    return config


class TestConfigExport:
    """Tests for GET /api/config/export."""

    def test_export_includes_instances_with_redacted_api_keys(self, client, user, instance):
        """Export should include instances with API keys redacted."""
        token = create_access_token(user.id, user.username)
        client.cookies.set("access_token", token)

        response = client.get("/api/config/export")
        assert response.status_code == 200

        data = response.json()
        assert len(data["instances"]) == 1
        assert data["instances"][0]["name"] == "Test Sonarr"
        assert data["instances"][0]["api_key"] == "[REDACTED]"
        assert data["instances"][0]["url"] == "https://sonarr.example.com"

    def test_export_includes_version_and_exported_at(self, client, user):
        """Export should include splintarr_version and exported_at fields."""
        token = create_access_token(user.id, user.username)
        client.cookies.set("access_token", token)

        response = client.get("/api/config/export")
        assert response.status_code == 200

        data = response.json()
        assert "splintarr_version" in data
        assert data["splintarr_version"] == "0.2.1"
        assert "exported_at" in data
        assert len(data["exported_at"]) > 0

    def test_export_includes_notification_config_redacted(self, client, user, notification_config):
        """Export should include notification config with webhook URL redacted."""
        token = create_access_token(user.id, user.username)
        client.cookies.set("access_token", token)

        response = client.get("/api/config/export")
        assert response.status_code == 200

        data = response.json()
        assert data["notifications"] is not None
        assert data["notifications"]["webhook_url"] == "[REDACTED]"
        assert data["notifications"]["is_active"] is True

    def test_export_has_content_disposition_header(self, client, user):
        """Export should set Content-Disposition header for download."""
        token = create_access_token(user.id, user.username)
        client.cookies.set("access_token", token)

        response = client.get("/api/config/export")
        assert response.status_code == 200
        assert "content-disposition" in response.headers
        assert "splintarr-config.json" in response.headers["content-disposition"]

    def test_export_requires_auth(self, client):
        """Export should return 401 without authentication."""
        response = client.get("/api/config/export")
        assert response.status_code == 401


class TestIntegrityCheck:
    """Tests for POST /api/config/integrity-check."""

    def test_integrity_check_returns_ok(self, client, user, db_engine):
        """Integrity check should return ok status on a healthy database."""
        token = create_access_token(user.id, user.username)
        client.cookies.set("access_token", token)

        # Patch get_engine to return the test engine
        from unittest.mock import patch

        with patch("splintarr.api.config.get_engine", return_value=db_engine):
            response = client.post("/api/config/integrity-check")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["details"] == ["ok"]

    def test_integrity_check_requires_auth(self, client):
        """Integrity check should return 401 without authentication."""
        response = client.post("/api/config/integrity-check")
        assert response.status_code == 401
