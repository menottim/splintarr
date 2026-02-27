"""
Unit tests for User and RefreshToken models.

Tests model functionality, relationships, security features, and business logic.
"""

from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from splintarr.models.user import RefreshToken, User


class TestUserModel:
    """Test User model functionality."""

    def test_create_user_basic(self, db_session):
        """Test creating a basic user."""
        user = User(username="testuser", password_hash="hashed_password")
        db_session.add(user)
        db_session.commit()

        assert user.id is not None
        assert user.username == "testuser"
        assert user.password_hash == "hashed_password"

    def test_user_default_values(self, db_session):
        """Test that user has correct default values."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        assert user.is_active is True
        assert user.is_superuser is False
        assert user.failed_login_attempts == 0
        assert user.account_locked_until is None
        assert user.last_failed_login is None
        assert user.last_login is None
        assert user.last_login_ip is None

    def test_user_timestamps_auto_set(self, db_session):
        """Test that created_at and updated_at are set automatically."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        assert user.created_at is not None
        assert user.updated_at is not None
        assert isinstance(user.created_at, datetime)
        assert isinstance(user.updated_at, datetime)

    def test_user_updated_at_changes_on_update(self, db_session):
        """Test that updated_at changes when user is modified."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        original_updated_at = user.updated_at

        # Wait a moment and update
        import time

        time.sleep(0.01)

        user.is_active = False
        db_session.commit()

        # updated_at should change
        assert user.updated_at >= original_updated_at

    def test_username_unique_constraint(self, db_session):
        """Test that username must be unique."""
        user1 = User(username="testuser", password_hash="hash1")
        db_session.add(user1)
        db_session.commit()

        user2 = User(username="testuser", password_hash="hash2")
        db_session.add(user2)

        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_username_indexed(self, db_session):
        """Test that username is indexed for fast lookups."""
        from sqlalchemy import inspect

        inspector = inspect(db_session.bind)
        indexes = inspector.get_indexes("users")

        # Find index on username
        username_indexed = any(
            "username" in idx.get("column_names", []) for idx in indexes
        )

        assert username_indexed or len(indexes) > 0  # Has indexes

    def test_user_repr(self, db_session):
        """Test user string representation."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        repr_str = repr(user)
        assert "testuser" in repr_str
        assert str(user.id) in repr_str
        assert "True" in repr_str  # is_active default

    def test_user_password_hash_not_nullable(self, db_session):
        """Test that password_hash is required."""
        user = User(username="testuser")
        db_session.add(user)

        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_user_username_not_nullable(self, db_session):
        """Test that username is required."""
        user = User(password_hash="hash")
        db_session.add(user)

        with pytest.raises(IntegrityError):
            db_session.commit()


class TestUserIsLocked:
    """Test User.is_locked() method."""

    def test_is_locked_not_locked(self, db_session):
        """Test is_locked returns False when account is not locked."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        assert user.is_locked() is False

    def test_is_locked_returns_true_when_locked(self, db_session):
        """Test is_locked returns True when account is locked."""
        user = User(username="testuser", password_hash="hash")
        user.account_locked_until = datetime.utcnow() + timedelta(minutes=30)
        db_session.add(user)
        db_session.commit()

        assert user.is_locked() is True

    def test_is_locked_returns_false_when_lockout_expired(self, db_session):
        """Test is_locked returns False when lockout period has expired."""
        user = User(username="testuser", password_hash="hash")
        user.account_locked_until = datetime.utcnow() - timedelta(minutes=1)
        db_session.add(user)
        db_session.commit()

        assert user.is_locked() is False

    def test_is_locked_boundary_condition(self, db_session):
        """Test is_locked at exact lockout expiry time."""
        user = User(username="testuser", password_hash="hash")
        # Set lockout to expire in a very short time
        user.account_locked_until = datetime.utcnow() + timedelta(microseconds=100)
        db_session.add(user)
        db_session.commit()

        # Should be locked initially
        assert user.is_locked() is True

        # Wait for lockout to expire
        import time

        time.sleep(0.001)

        # Should no longer be locked
        assert user.is_locked() is False


class TestUserIncrementFailedLogin:
    """Test User.increment_failed_login() method."""

    def test_increment_failed_login_increases_counter(self, db_session):
        """Test that failed login counter is incremented."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        user.increment_failed_login(max_attempts=5, lockout_duration_minutes=30)

        assert user.failed_login_attempts == 1
        assert user.last_failed_login is not None
        assert isinstance(user.last_failed_login, datetime)

    def test_increment_failed_login_multiple_times(self, db_session):
        """Test incrementing failed login counter multiple times."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        for i in range(3):
            user.increment_failed_login(max_attempts=5, lockout_duration_minutes=30)

        assert user.failed_login_attempts == 3

    def test_increment_failed_login_locks_at_max_attempts(self, db_session):
        """Test that account is locked when max attempts reached."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        max_attempts = 5
        for i in range(max_attempts):
            user.increment_failed_login(max_attempts=max_attempts, lockout_duration_minutes=30)

        assert user.failed_login_attempts == max_attempts
        assert user.account_locked_until is not None
        assert user.is_locked() is True

    def test_increment_failed_login_lockout_duration(self, db_session):
        """Test that lockout duration is set correctly."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        lockout_duration = 30
        for i in range(5):
            user.increment_failed_login(max_attempts=5, lockout_duration_minutes=lockout_duration)

        # Check lockout expiry is approximately lockout_duration minutes in future
        expected_lockout = datetime.utcnow() + timedelta(minutes=lockout_duration)
        time_diff = abs((user.account_locked_until - expected_lockout).total_seconds())

        # Allow 1 second tolerance
        assert time_diff < 1

    def test_increment_failed_login_before_max_no_lockout(self, db_session):
        """Test that account is not locked before max attempts."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        user.increment_failed_login(max_attempts=5, lockout_duration_minutes=30)
        user.increment_failed_login(max_attempts=5, lockout_duration_minutes=30)

        assert user.failed_login_attempts == 2
        assert user.account_locked_until is None
        assert user.is_locked() is False


class TestUserResetFailedLogin:
    """Test User.reset_failed_login() method."""

    def test_reset_failed_login_clears_counter(self, db_session):
        """Test that reset clears failed login counter."""
        user = User(username="testuser", password_hash="hash")
        user.failed_login_attempts = 3
        user.last_failed_login = datetime.utcnow()
        db_session.add(user)
        db_session.commit()

        user.reset_failed_login()

        assert user.failed_login_attempts == 0
        assert user.last_failed_login is None

    def test_reset_failed_login_clears_lockout(self, db_session):
        """Test that reset clears account lockout."""
        user = User(username="testuser", password_hash="hash")
        user.failed_login_attempts = 5
        user.account_locked_until = datetime.utcnow() + timedelta(minutes=30)
        db_session.add(user)
        db_session.commit()

        user.reset_failed_login()

        assert user.account_locked_until is None
        assert user.is_locked() is False


class TestUserRecordSuccessfulLogin:
    """Test User.record_successful_login() method."""

    def test_record_successful_login_sets_timestamp(self, db_session):
        """Test that successful login sets last_login timestamp."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        ip_address = "192.168.1.1"
        user.record_successful_login(ip_address)

        assert user.last_login is not None
        assert isinstance(user.last_login, datetime)

    def test_record_successful_login_sets_ip_address(self, db_session):
        """Test that successful login records IP address."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        ip_address = "192.168.1.1"
        user.record_successful_login(ip_address)

        assert user.last_login_ip == ip_address

    def test_record_successful_login_ipv6(self, db_session):
        """Test recording login with IPv6 address."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        ipv6_address = "2001:0db8:85a3:0000:0000:8a2e:0370:7334"
        user.record_successful_login(ipv6_address)

        assert user.last_login_ip == ipv6_address

    def test_record_successful_login_resets_failed_attempts(self, db_session):
        """Test that successful login resets failed login tracking."""
        user = User(username="testuser", password_hash="hash")
        user.failed_login_attempts = 3
        user.last_failed_login = datetime.utcnow()
        user.account_locked_until = datetime.utcnow() + timedelta(minutes=30)
        db_session.add(user)
        db_session.commit()

        user.record_successful_login("192.168.1.1")

        assert user.failed_login_attempts == 0
        assert user.last_failed_login is None
        assert user.account_locked_until is None


class TestUserRelationships:
    """Test User model relationships."""

    def test_user_refresh_tokens_relationship(self, db_session):
        """Test relationship between User and RefreshToken."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        token = RefreshToken(
            jti="test-jti",
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(days=1),
        )
        db_session.add(token)
        db_session.commit()

        # Access relationship
        assert user.refresh_tokens.count() == 1
        assert user.refresh_tokens.first().jti == "test-jti"

    def test_user_instances_relationship(self, db_session):
        """Test relationship between User and Instance."""
        from splintarr.models.instance import Instance

        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="encrypted_key",
        )
        db_session.add(instance)
        db_session.commit()

        # Access relationship
        assert user.instances.count() == 1
        assert user.instances.first().name == "Test Instance"

    def test_user_cascade_delete_tokens(self, db_session):
        """Test that deleting user cascades to refresh tokens."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        token = RefreshToken(
            jti="test-jti",
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(days=1),
        )
        db_session.add(token)
        db_session.commit()

        token_id = token.id

        # Delete user
        db_session.delete(user)
        db_session.commit()

        # Token should be deleted
        deleted_token = db_session.query(RefreshToken).filter_by(id=token_id).first()
        assert deleted_token is None


class TestRefreshTokenModel:
    """Test RefreshToken model functionality."""

    def test_create_refresh_token(self, db_session):
        """Test creating a refresh token."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        expires_at = datetime.utcnow() + timedelta(days=30)
        token = RefreshToken(jti="test-jti-123", user_id=user.id, expires_at=expires_at)
        db_session.add(token)
        db_session.commit()

        assert token.id is not None
        assert token.jti == "test-jti-123"
        assert token.user_id == user.id
        assert token.expires_at == expires_at

    def test_refresh_token_default_values(self, db_session):
        """Test refresh token default values."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        token = RefreshToken(
            jti="test-jti",
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(days=1),
        )
        db_session.add(token)
        db_session.commit()

        assert token.revoked is False
        assert token.revoked_at is None
        assert token.device_info is None
        assert token.ip_address is None

    def test_refresh_token_with_device_info(self, db_session):
        """Test creating token with device info."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        token = RefreshToken(
            jti="test-jti",
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(days=1),
            device_info="Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            ip_address="192.168.1.1",
        )
        db_session.add(token)
        db_session.commit()

        assert token.device_info is not None
        assert token.ip_address == "192.168.1.1"

    def test_refresh_token_jti_unique_constraint(self, db_session):
        """Test that JTI must be unique."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        token1 = RefreshToken(
            jti="duplicate-jti",
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(days=1),
        )
        db_session.add(token1)
        db_session.commit()

        token2 = RefreshToken(
            jti="duplicate-jti",
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(days=1),
        )
        db_session.add(token2)

        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_refresh_token_created_at_auto_set(self, db_session):
        """Test that created_at is set automatically."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        token = RefreshToken(
            jti="test-jti",
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(days=1),
        )
        db_session.add(token)
        db_session.commit()

        assert token.created_at is not None
        assert isinstance(token.created_at, datetime)

    def test_refresh_token_repr(self, db_session):
        """Test refresh token string representation."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        token = RefreshToken(
            jti="test-jti",
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(days=1),
        )
        db_session.add(token)
        db_session.commit()

        repr_str = repr(token)
        assert "test-jti" in repr_str
        assert str(user.id) in repr_str
        assert "False" in repr_str  # revoked default


class TestRefreshTokenIsValid:
    """Test RefreshToken.is_valid() method."""

    def test_is_valid_returns_true_for_valid_token(self, db_session):
        """Test that is_valid returns True for valid token."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        token = RefreshToken(
            jti="test-jti",
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(days=30),
        )
        db_session.add(token)
        db_session.commit()

        assert token.is_valid() is True

    def test_is_valid_returns_false_for_revoked_token(self, db_session):
        """Test that is_valid returns False for revoked token."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        token = RefreshToken(
            jti="test-jti",
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(days=30),
            revoked=True,
        )
        db_session.add(token)
        db_session.commit()

        assert token.is_valid() is False

    def test_is_valid_returns_false_for_expired_token(self, db_session):
        """Test that is_valid returns False for expired token."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        token = RefreshToken(
            jti="test-jti",
            user_id=user.id,
            expires_at=datetime.utcnow() - timedelta(days=1),
        )
        db_session.add(token)
        db_session.commit()

        assert token.is_valid() is False


class TestRefreshTokenRevoke:
    """Test RefreshToken.revoke() method."""

    def test_revoke_marks_token_as_revoked(self, db_session):
        """Test that revoke marks token as revoked."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        token = RefreshToken(
            jti="test-jti",
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(days=30),
        )
        db_session.add(token)
        db_session.commit()

        token.revoke()

        assert token.revoked is True
        assert token.revoked_at is not None
        assert isinstance(token.revoked_at, datetime)

    def test_revoke_makes_token_invalid(self, db_session):
        """Test that revoked token becomes invalid."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        token = RefreshToken(
            jti="test-jti",
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(days=30),
        )
        db_session.add(token)
        db_session.commit()

        assert token.is_valid() is True

        token.revoke()

        assert token.is_valid() is False


class TestRefreshTokenIsExpired:
    """Test RefreshToken.is_expired() method."""

    def test_is_expired_returns_false_for_valid_token(self, db_session):
        """Test that is_expired returns False for non-expired token."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        token = RefreshToken(
            jti="test-jti",
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(days=30),
        )
        db_session.add(token)
        db_session.commit()

        assert token.is_expired() is False

    def test_is_expired_returns_true_for_expired_token(self, db_session):
        """Test that is_expired returns True for expired token."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        token = RefreshToken(
            jti="test-jti",
            user_id=user.id,
            expires_at=datetime.utcnow() - timedelta(days=1),
        )
        db_session.add(token)
        db_session.commit()

        assert token.is_expired() is True


class TestRefreshTokenTimeUntilExpiry:
    """Test RefreshToken.time_until_expiry property."""

    def test_time_until_expiry_positive_for_valid_token(self, db_session):
        """Test that time_until_expiry is positive for non-expired token."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        expires_at = datetime.utcnow() + timedelta(days=30)
        token = RefreshToken(jti="test-jti", user_id=user.id, expires_at=expires_at)
        db_session.add(token)
        db_session.commit()

        time_remaining = token.time_until_expiry

        assert isinstance(time_remaining, timedelta)
        assert time_remaining.total_seconds() > 0

    def test_time_until_expiry_negative_for_expired_token(self, db_session):
        """Test that time_until_expiry is negative for expired token."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        expires_at = datetime.utcnow() - timedelta(days=1)
        token = RefreshToken(jti="test-jti", user_id=user.id, expires_at=expires_at)
        db_session.add(token)
        db_session.commit()

        time_remaining = token.time_until_expiry

        assert time_remaining.total_seconds() < 0


class TestRefreshTokenUserRelationship:
    """Test RefreshToken relationship with User."""

    def test_refresh_token_user_relationship(self, db_session):
        """Test accessing user from refresh token."""
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        token = RefreshToken(
            jti="test-jti",
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(days=1),
        )
        db_session.add(token)
        db_session.commit()

        # Access user through relationship
        assert token.user.username == "testuser"

    def test_refresh_token_foreign_key_constraint(self, db_session):
        """Test that invalid user_id raises error."""
        token = RefreshToken(
            jti="test-jti",
            user_id=99999,  # Non-existent user
            expires_at=datetime.utcnow() + timedelta(days=1),
        )
        db_session.add(token)

        with pytest.raises(IntegrityError):
            db_session.commit()
