"""
Unit tests for Instance model health monitoring columns and methods (v0.2.1).

Tests cover:
- New column defaults (consecutive_failures, consecutive_successes, last_healthy_at, response_time_ms)
- mark_healthy() resets failures, increments successes, sets last_healthy_at, stores response_time_ms
- mark_unhealthy() increments failures, resets successes, stores error
- record_connection_test() stores response_time_ms
- connection_status property still works correctly with new method behavior
"""

from datetime import datetime

from splintarr.models.instance import Instance
from splintarr.models.user import User


def _create_instance(db_session, **overrides):
    """Helper to create a User + Instance pair and return the committed Instance."""
    user = User(username="testuser", password_hash="hash")
    db_session.add(user)
    db_session.commit()

    defaults = {
        "user_id": user.id,
        "name": "Test Instance",
        "instance_type": "sonarr",
        "url": "https://sonarr.example.com",
        "api_key": "encrypted_key",
    }
    defaults.update(overrides)
    instance = Instance(**defaults)
    db_session.add(instance)
    db_session.commit()
    return instance


class TestHealthColumnDefaults:
    """New health monitoring columns default correctly after creation."""

    def test_consecutive_failures_defaults_to_zero(self, db_session):
        instance = _create_instance(db_session)
        assert instance.consecutive_failures == 0

    def test_consecutive_successes_defaults_to_zero(self, db_session):
        instance = _create_instance(db_session)
        assert instance.consecutive_successes == 0

    def test_last_healthy_at_defaults_to_none(self, db_session):
        instance = _create_instance(db_session)
        assert instance.last_healthy_at is None

    def test_response_time_ms_defaults_to_none(self, db_session):
        instance = _create_instance(db_session)
        assert instance.response_time_ms is None


class TestMarkHealthy:
    """mark_healthy() updates all health tracking fields correctly."""

    def test_sets_last_connection_success_true(self, db_session):
        instance = _create_instance(db_session)
        instance.mark_healthy(response_time_ms=150)
        assert instance.last_connection_success is True

    def test_clears_connection_error(self, db_session):
        instance = _create_instance(db_session)
        instance.connection_error = "previous error"
        instance.mark_healthy()
        assert instance.connection_error is None

    def test_resets_consecutive_failures_to_zero(self, db_session):
        instance = _create_instance(db_session)
        instance.consecutive_failures = 3
        instance.mark_healthy()
        assert instance.consecutive_failures == 0

    def test_increments_consecutive_successes(self, db_session):
        instance = _create_instance(db_session)
        assert instance.consecutive_successes == 0

        instance.mark_healthy()
        assert instance.consecutive_successes == 1

        instance.mark_healthy()
        assert instance.consecutive_successes == 2

    def test_sets_last_healthy_at(self, db_session):
        instance = _create_instance(db_session)
        assert instance.last_healthy_at is None

        before = datetime.utcnow()
        instance.mark_healthy()
        after = datetime.utcnow()

        assert instance.last_healthy_at is not None
        assert before <= instance.last_healthy_at <= after

    def test_stores_response_time_ms(self, db_session):
        instance = _create_instance(db_session)
        instance.mark_healthy(response_time_ms=250)
        assert instance.response_time_ms == 250

    def test_response_time_ms_defaults_to_none(self, db_session):
        instance = _create_instance(db_session)
        instance.mark_healthy()
        assert instance.response_time_ms is None

    def test_sets_last_connection_test_timestamp(self, db_session):
        instance = _create_instance(db_session)
        before = datetime.utcnow()
        instance.mark_healthy()
        after = datetime.utcnow()
        assert before <= instance.last_connection_test <= after

    def test_is_healthy_returns_true_after_mark_healthy(self, db_session):
        instance = _create_instance(db_session)
        instance.mark_healthy()
        assert instance.is_healthy() is True


class TestMarkUnhealthy:
    """mark_unhealthy() updates all health tracking fields correctly."""

    def test_sets_last_connection_success_false(self, db_session):
        instance = _create_instance(db_session)
        instance.mark_unhealthy("Connection refused")
        assert instance.last_connection_success is False

    def test_stores_error_message(self, db_session):
        instance = _create_instance(db_session)
        instance.mark_unhealthy("API key invalid")
        assert instance.connection_error == "API key invalid"

    def test_increments_consecutive_failures(self, db_session):
        instance = _create_instance(db_session)
        assert instance.consecutive_failures == 0

        instance.mark_unhealthy("error 1")
        assert instance.consecutive_failures == 1

        instance.mark_unhealthy("error 2")
        assert instance.consecutive_failures == 2

    def test_resets_consecutive_successes_to_zero(self, db_session):
        instance = _create_instance(db_session)
        instance.consecutive_successes = 5
        instance.mark_unhealthy("Connection timeout")
        assert instance.consecutive_successes == 0

    def test_sets_last_connection_test_timestamp(self, db_session):
        instance = _create_instance(db_session)
        before = datetime.utcnow()
        instance.mark_unhealthy("timeout")
        after = datetime.utcnow()
        assert before <= instance.last_connection_test <= after

    def test_is_healthy_returns_false_after_mark_unhealthy(self, db_session):
        instance = _create_instance(db_session)
        instance.mark_unhealthy("error")
        assert instance.is_healthy() is False

    def test_does_not_update_last_healthy_at(self, db_session):
        instance = _create_instance(db_session)
        instance.mark_healthy(response_time_ms=100)
        healthy_time = instance.last_healthy_at

        instance.mark_unhealthy("error")
        assert instance.last_healthy_at == healthy_time


class TestRecordConnectionTest:
    """record_connection_test() stores response_time_ms alongside existing fields."""

    def test_stores_response_time_ms_on_success(self, db_session):
        instance = _create_instance(db_session)
        instance.record_connection_test(success=True, response_time_ms=200)
        assert instance.response_time_ms == 200
        assert instance.last_connection_success is True
        assert instance.connection_error is None

    def test_stores_response_time_ms_on_failure(self, db_session):
        instance = _create_instance(db_session)
        instance.record_connection_test(success=False, error="timeout", response_time_ms=5000)
        assert instance.response_time_ms == 5000
        assert instance.last_connection_success is False
        assert instance.connection_error == "timeout"

    def test_response_time_ms_optional(self, db_session):
        """Backward compatibility: record_connection_test works without response_time_ms."""
        instance = _create_instance(db_session)
        instance.record_connection_test(success=True)
        assert instance.response_time_ms is None
        assert instance.last_connection_success is True


class TestConnectionStatusProperty:
    """connection_status property works correctly with the updated methods."""

    def test_untested_by_default(self, db_session):
        instance = _create_instance(db_session)
        assert instance.connection_status == "untested"

    def test_healthy_after_mark_healthy(self, db_session):
        instance = _create_instance(db_session)
        instance.mark_healthy(response_time_ms=100)
        assert instance.connection_status == "healthy"

    def test_unhealthy_after_mark_unhealthy(self, db_session):
        instance = _create_instance(db_session)
        instance.mark_unhealthy("Connection refused")
        assert instance.connection_status == "unhealthy"

    def test_healthy_then_unhealthy(self, db_session):
        instance = _create_instance(db_session)
        instance.mark_healthy()
        assert instance.connection_status == "healthy"

        instance.mark_unhealthy("went down")
        assert instance.connection_status == "unhealthy"

    def test_unhealthy_then_healthy(self, db_session):
        instance = _create_instance(db_session)
        instance.mark_unhealthy("down")
        assert instance.connection_status == "unhealthy"

        instance.mark_healthy()
        assert instance.connection_status == "healthy"


class TestHealthTransitions:
    """End-to-end transition scenarios for health counters."""

    def test_alternating_healthy_unhealthy(self, db_session):
        """Counters reset correctly when health flips back and forth."""
        instance = _create_instance(db_session)

        instance.mark_healthy(response_time_ms=100)
        assert instance.consecutive_successes == 1
        assert instance.consecutive_failures == 0

        instance.mark_unhealthy("timeout")
        assert instance.consecutive_successes == 0
        assert instance.consecutive_failures == 1

        instance.mark_healthy(response_time_ms=80)
        assert instance.consecutive_successes == 1
        assert instance.consecutive_failures == 0

    def test_multiple_failures_then_recovery(self, db_session):
        """Consecutive failures accumulate then reset on recovery."""
        instance = _create_instance(db_session)

        instance.mark_unhealthy("error 1")
        instance.mark_unhealthy("error 2")
        instance.mark_unhealthy("error 3")
        assert instance.consecutive_failures == 3
        assert instance.consecutive_successes == 0

        instance.mark_healthy(response_time_ms=150)
        assert instance.consecutive_failures == 0
        assert instance.consecutive_successes == 1
        assert instance.last_healthy_at is not None

    def test_last_healthy_at_preserved_across_failures(self, db_session):
        """last_healthy_at stays set even after multiple failures."""
        instance = _create_instance(db_session)
        instance.mark_healthy()
        healthy_time = instance.last_healthy_at

        instance.mark_unhealthy("down 1")
        instance.mark_unhealthy("down 2")

        assert instance.last_healthy_at == healthy_time
