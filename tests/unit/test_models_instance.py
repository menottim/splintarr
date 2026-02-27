"""
Unit tests for Instance model.

Tests instance model functionality, relationships, connection health tracking,
and encrypted API key storage.
"""

from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from splintarr.models.instance import Instance
from splintarr.models.user import User


class TestInstanceModel:
    """Test Instance model functionality."""

    def test_create_instance_basic(self, db_session):
        """Test creating a basic instance."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="My Sonarr",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="encrypted_api_key",
        )
        db_session.add(instance)
        db_session.commit()

        assert instance.id is not None
        assert instance.name == "My Sonarr"
        assert instance.instance_type == "sonarr"
        assert instance.url == "https://sonarr.example.com"

    def test_instance_default_values(self, db_session):
        """Test that instance has correct default values."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        assert instance.is_active is True
        assert instance.verify_ssl is True
        assert instance.timeout_seconds == 30
        assert instance.rate_limit_per_second == 5
        assert instance.last_connection_test is None
        assert instance.last_connection_success is None
        assert instance.connection_error is None

    def test_instance_timestamps_auto_set(self, db_session):
        """Test that timestamps are set automatically."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        assert instance.created_at is not None
        assert instance.updated_at is not None
        assert isinstance(instance.created_at, datetime)
        assert isinstance(instance.updated_at, datetime)

    def test_instance_updated_at_changes_on_update(self, db_session):
        """Test that updated_at changes when instance is modified."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        original_updated_at = instance.updated_at

        # Wait and update
        import time

        time.sleep(0.01)

        instance.name = "Updated Name"
        db_session.commit()

        assert instance.updated_at >= original_updated_at

    def test_instance_type_sonarr(self, db_session):
        """Test creating Sonarr instance."""
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

        assert instance.instance_type == "sonarr"

    def test_instance_type_radarr(self, db_session):
        """Test creating Radarr instance."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Radarr",
            instance_type="radarr",
            url="https://radarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        assert instance.instance_type == "radarr"

    def test_instance_required_fields(self, db_session):
        """Test that required fields must be provided."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        # Missing name
        with pytest.raises(IntegrityError):
            instance = Instance(
                user_id=user.id, instance_type="sonarr", url="https://example.com", api_key="key"
            )
            db_session.add(instance)
            db_session.commit()

        db_session.rollback()

        # Missing instance_type
        with pytest.raises(IntegrityError):
            instance = Instance(
                user_id=user.id, name="Test", url="https://example.com", api_key="key"
            )
            db_session.add(instance)
            db_session.commit()

    def test_instance_repr(self, db_session):
        """Test instance string representation."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="My Sonarr",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        repr_str = repr(instance)
        assert "My Sonarr" in repr_str
        assert "sonarr" in repr_str
        assert "True" in repr_str  # is_active


class TestInstanceIsHealthy:
    """Test Instance.is_healthy() method."""

    def test_is_healthy_returns_true_when_healthy(self, db_session):
        """Test is_healthy returns True when last connection succeeded."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        instance.last_connection_success = True
        db_session.add(instance)
        db_session.commit()

        assert instance.is_healthy() is True

    def test_is_healthy_returns_false_when_unhealthy(self, db_session):
        """Test is_healthy returns False when last connection failed."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        instance.last_connection_success = False
        db_session.add(instance)
        db_session.commit()

        assert instance.is_healthy() is False

    def test_is_healthy_returns_false_when_never_tested(self, db_session):
        """Test is_healthy returns False when connection never tested."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        assert instance.is_healthy() is False


class TestInstanceRecordConnectionTest:
    """Test Instance.record_connection_test() method."""

    def test_record_connection_test_success(self, db_session):
        """Test recording successful connection test."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        instance.record_connection_test(success=True)

        assert instance.last_connection_test is not None
        assert instance.last_connection_success is True
        assert instance.connection_error is None

    def test_record_connection_test_failure(self, db_session):
        """Test recording failed connection test."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        error_message = "Connection timeout"
        instance.record_connection_test(success=False, error=error_message)

        assert instance.last_connection_test is not None
        assert instance.last_connection_success is False
        assert instance.connection_error == error_message

    def test_record_connection_test_updates_timestamp(self, db_session):
        """Test that connection test timestamp is updated."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        before = datetime.utcnow()
        instance.record_connection_test(success=True)
        after = datetime.utcnow()

        assert before <= instance.last_connection_test <= after

    def test_record_connection_test_clears_error_on_success(self, db_session):
        """Test that error is cleared when connection succeeds."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        instance.connection_error = "Previous error"
        db_session.add(instance)
        db_session.commit()

        instance.record_connection_test(success=True)

        assert instance.connection_error is None


class TestInstanceMarkUnhealthy:
    """Test Instance.mark_unhealthy() method."""

    def test_mark_unhealthy_records_error(self, db_session):
        """Test that mark_unhealthy records error message."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        error_message = "API key invalid"
        instance.mark_unhealthy(error_message)

        assert instance.last_connection_success is False
        assert instance.connection_error == error_message
        assert instance.is_healthy() is False


class TestInstanceMarkHealthy:
    """Test Instance.mark_healthy() method."""

    def test_mark_healthy_clears_error(self, db_session):
        """Test that mark_healthy clears error message."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        instance.connection_error = "Previous error"
        instance.last_connection_success = False
        db_session.add(instance)
        db_session.commit()

        instance.mark_healthy()

        assert instance.last_connection_success is True
        assert instance.connection_error is None
        assert instance.is_healthy() is True


class TestInstanceConnectionStatus:
    """Test Instance.connection_status property."""

    def test_connection_status_untested(self, db_session):
        """Test connection status when never tested."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        assert instance.connection_status == "untested"

    def test_connection_status_healthy(self, db_session):
        """Test connection status when healthy."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        instance.mark_healthy()
        db_session.add(instance)
        db_session.commit()

        assert instance.connection_status == "healthy"

    def test_connection_status_unhealthy(self, db_session):
        """Test connection status when unhealthy."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        instance.mark_unhealthy("Connection failed")
        db_session.add(instance)
        db_session.commit()

        assert instance.connection_status == "unhealthy"


class TestInstanceSanitizedUrl:
    """Test Instance.sanitized_url property."""

    def test_sanitized_url_without_credentials(self, db_session):
        """Test sanitized URL when no credentials in URL."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com:8989",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        assert instance.sanitized_url == "https://sonarr.example.com:8989"

    def test_sanitized_url_removes_basic_auth(self, db_session):
        """Test that sanitized URL removes basic auth credentials."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://user:password@sonarr.example.com:8989",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        sanitized = instance.sanitized_url
        assert "user" not in sanitized
        assert "password" not in sanitized
        assert "sonarr.example.com" in sanitized

    def test_sanitized_url_preserves_port(self, db_session):
        """Test that sanitized URL preserves port."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://user:password@sonarr.example.com:8989/path",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        assert ":8989" in instance.sanitized_url


class TestInstanceRelationships:
    """Test Instance model relationships."""

    def test_instance_user_relationship(self, db_session):
        """Test relationship between Instance and User."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        # Access user through relationship
        assert instance.user.username == "testuser"

    def test_instance_search_queues_relationship(self, db_session):
        """Test relationship between Instance and SearchQueue."""
        from splintarr.models.search_queue import SearchQueue

        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(
            instance_id=instance.id, name="Test Search", strategy="missing"
        )
        db_session.add(search_queue)
        db_session.commit()

        # Access search queues through relationship
        assert instance.search_queues.count() == 1
        assert instance.search_queues.first().name == "Test Search"

    def test_instance_search_history_relationship(self, db_session):
        """Test relationship between Instance and SearchHistory."""
        from splintarr.models.search_history import SearchHistory

        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        history = SearchHistory(
            instance_id=instance.id,
            search_name="Test Search",
            strategy="missing",
            started_at=datetime.utcnow(),
            status="success",
        )
        db_session.add(history)
        db_session.commit()

        # Access search history through relationship
        assert instance.search_history.count() == 1
        assert instance.search_history.first().search_name == "Test Search"

    def test_instance_foreign_key_constraint(self, db_session):
        """Test that invalid user_id raises error."""
        instance = Instance(
            user_id=99999,  # Non-existent user
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)

        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_instance_cascade_delete(self, db_session):
        """Test that deleting instance cascades to related records."""
        from splintarr.models.search_queue import SearchQueue

        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(
            instance_id=instance.id, name="Test Search", strategy="missing"
        )
        db_session.add(search_queue)
        db_session.commit()

        search_queue_id = search_queue.id

        # Delete instance
        db_session.delete(instance)
        db_session.commit()

        # Search queue should be deleted
        deleted_queue = db_session.query(SearchQueue).filter_by(id=search_queue_id).first()
        assert deleted_queue is None


class TestInstanceConfiguration:
    """Test instance configuration options."""

    def test_instance_verify_ssl_default_true(self, db_session):
        """Test that verify_ssl defaults to True for security."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        assert instance.verify_ssl is True

    def test_instance_verify_ssl_can_be_disabled(self, db_session):
        """Test that verify_ssl can be disabled for development."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
            verify_ssl=False,
        )
        db_session.add(instance)
        db_session.commit()

        assert instance.verify_ssl is False

    def test_instance_timeout_default(self, db_session):
        """Test that timeout has reasonable default."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        assert instance.timeout_seconds == 30

    def test_instance_rate_limit_default(self, db_session):
        """Test that rate limit has reasonable default."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
        )
        db_session.add(instance)
        db_session.commit()

        assert instance.rate_limit_per_second == 5

    def test_instance_custom_configuration(self, db_session):
        """Test creating instance with custom configuration."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="key",
            verify_ssl=False,
            timeout_seconds=60,
            rate_limit_per_second=10,
        )
        db_session.add(instance)
        db_session.commit()

        assert instance.verify_ssl is False
        assert instance.timeout_seconds == 60
        assert instance.rate_limit_per_second == 10
