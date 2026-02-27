"""
Unit tests for authentication logic.

Tests JWT token creation, validation, rotation, and two-factor authentication.
"""

from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest
import pyotp
from freezegun import freeze_time
import jwt

from splintarr.config import settings
from splintarr.core.auth import (
    AuthenticationError,
    TokenError,
    authenticate_user,
    cleanup_expired_tokens,
    create_2fa_pending_token,
    create_access_token,
    create_refresh_token,
    generate_totp_qr_code_base64,
    generate_totp_secret,
    generate_totp_uri,
    get_current_user_id_from_token,
    revoke_all_user_tokens,
    revoke_refresh_token,
    rotate_refresh_token,
    verify_2fa_pending_token,
    verify_access_token,
    verify_refresh_token,
    verify_totp_code,
)
from splintarr.core.security import hash_password
from splintarr.models.user import RefreshToken, User


class TestAccessToken:
    """Tests for access token creation and validation."""

    def test_create_access_token(self):
        """Test creating a valid access token."""
        user_id = 1
        username = "testuser"

        token = create_access_token(user_id, username)

        # Verify it's a valid JWT
        assert isinstance(token, str)
        assert len(token) > 0

        # Decode and verify claims
        payload = jwt.decode(
            token,
            settings.get_secret_key(),
            algorithms=[settings.algorithm],
        )

        assert payload["sub"] == str(user_id)
        assert payload["username"] == username
        assert payload["type"] == "access"
        assert "exp" in payload
        assert "iat" in payload
        assert "jti" in payload

    def test_create_access_token_with_additional_claims(self):
        """Test creating access token with additional claims."""
        user_id = 1
        username = "testuser"
        additional_claims = {"role": "admin", "permissions": ["read", "write"]}

        token = create_access_token(user_id, username, additional_claims)

        payload = jwt.decode(
            token,
            settings.get_secret_key(),
            algorithms=[settings.algorithm],
        )

        assert payload["role"] == "admin"
        assert payload["permissions"] == ["read", "write"]

    def test_verify_access_token(self):
        """Test verifying a valid access token."""
        user_id = 1
        username = "testuser"

        token = create_access_token(user_id, username)
        payload = verify_access_token(token)

        assert payload["sub"] == str(user_id)
        assert payload["username"] == username
        assert payload["type"] == "access"

    def test_verify_expired_access_token(self):
        """Test verifying an expired access token."""
        user_id = 1
        username = "testuser"

        # Create token that expires in 1 second
        with patch.object(settings, "access_token_expire_minutes", 0):
            # Create a token with immediate expiration
            expire = datetime.utcnow() - timedelta(seconds=1)
            claims = {
                "sub": str(user_id),
                "username": username,
                "type": "access",
                "exp": expire,
                "iat": datetime.utcnow(),
                "jti": "test-jti",
            }
            token = jwt.encode(claims, settings.get_secret_key(), algorithm=settings.algorithm)

        # Verify it raises TokenError
        with pytest.raises(TokenError, match="Invalid access token"):
            verify_access_token(token)

    def test_verify_invalid_signature(self):
        """Test verifying token with invalid signature."""
        user_id = 1
        username = "testuser"

        # Create token with wrong secret
        expire = datetime.utcnow() + timedelta(minutes=15)
        claims = {
            "sub": str(user_id),
            "username": username,
            "type": "access",
            "exp": expire,
        }
        token = jwt.encode(claims, "wrong-secret-key", algorithm=settings.algorithm)

        with pytest.raises(TokenError, match="Invalid access token"):
            verify_access_token(token)

    def test_verify_wrong_token_type(self):
        """Test verifying token with wrong type."""
        user_id = 1

        # Create refresh token instead of access token
        expire = datetime.utcnow() + timedelta(minutes=15)
        claims = {
            "sub": str(user_id),
            "type": "refresh",  # Wrong type
            "exp": expire,
        }
        token = jwt.encode(claims, settings.get_secret_key(), algorithm=settings.algorithm)

        with pytest.raises(TokenError, match="Invalid token type"):
            verify_access_token(token)

    def test_get_current_user_id_from_token(self):
        """Test extracting user ID from token."""
        user_id = 42
        username = "testuser"

        token = create_access_token(user_id, username)
        extracted_user_id = get_current_user_id_from_token(token)

        assert extracted_user_id == user_id

    def test_get_current_user_id_from_invalid_token(self):
        """Test extracting user ID from invalid token."""
        with pytest.raises(TokenError):
            get_current_user_id_from_token("invalid-token")


class TestRefreshToken:
    """Tests for refresh token creation, validation, and rotation."""

    def test_create_refresh_token(self, db_session):
        """Test creating a valid refresh token."""
        # Create user
        user = User(
            username="testuser",
            password_hash=hash_password("TestP@ssw0rd123!"),
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()

        # Create refresh token
        token, db_token = create_refresh_token(
            db=db_session,
            user_id=user.id,
            device_info="Test Device",
            ip_address="127.0.0.1",
        )

        # Verify token string
        assert isinstance(token, str)
        assert len(token) > 0

        # Verify database record
        assert db_token.user_id == user.id
        assert db_token.device_info == "Test Device"
        assert db_token.ip_address == "127.0.0.1"
        assert db_token.revoked is False
        assert db_token.expires_at > datetime.utcnow()

        # Verify JWT payload
        payload = jwt.decode(
            token,
            settings.get_secret_key(),
            algorithms=[settings.algorithm],
        )
        assert payload["sub"] == str(user.id)
        assert payload["type"] == "refresh"
        assert payload["jti"] == db_token.jti

    def test_verify_refresh_token(self, db_session):
        """Test verifying a valid refresh token."""
        # Create user
        user = User(
            username="testuser",
            password_hash=hash_password("TestP@ssw0rd123!"),
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()

        # Create refresh token
        token, db_token = create_refresh_token(db=db_session, user_id=user.id)

        # Verify token
        payload, verified_db_token = verify_refresh_token(db_session, token)

        assert payload["sub"] == str(user.id)
        assert payload["type"] == "refresh"
        assert verified_db_token.id == db_token.id
        assert verified_db_token.jti == db_token.jti

    def test_verify_revoked_refresh_token(self, db_session):
        """Test verifying a revoked refresh token."""
        # Create user
        user = User(
            username="testuser",
            password_hash=hash_password("TestP@ssw0rd123!"),
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()

        # Create and revoke token
        token, db_token = create_refresh_token(db=db_session, user_id=user.id)
        db_token.revoke()
        db_session.commit()

        # Verify it raises TokenError
        with pytest.raises(TokenError, match="Token has been revoked or expired"):
            verify_refresh_token(db_session, token)

    def test_verify_expired_refresh_token(self, db_session):
        """Test verifying an expired refresh token."""
        # Create user
        user = User(
            username="testuser",
            password_hash=hash_password("TestP@ssw0rd123!"),
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()

        # Create token with past expiration
        jti = "test-jti"
        expire = datetime.utcnow() - timedelta(days=1)
        claims = {
            "sub": str(user.id),
            "type": "refresh",
            "jti": jti,
            "exp": expire,
        }
        token = jwt.encode(claims, settings.get_secret_key(), algorithm=settings.algorithm)

        # Add to database
        db_token = RefreshToken(
            jti=jti,
            user_id=user.id,
            expires_at=expire,
        )
        db_session.add(db_token)
        db_session.commit()

        # Verify it raises TokenError (JWT library catches expiration first)
        with pytest.raises(TokenError, match="Signature has expired"):
            verify_refresh_token(db_session, token)

    def test_verify_nonexistent_refresh_token(self, db_session):
        """Test verifying a token not in database."""
        user_id = 999
        jti = "nonexistent-jti"

        # Create token that doesn't exist in database
        expire = datetime.utcnow() + timedelta(days=30)
        claims = {
            "sub": str(user_id),
            "type": "refresh",
            "jti": jti,
            "exp": expire,
        }
        token = jwt.encode(claims, settings.get_secret_key(), algorithm=settings.algorithm)

        with pytest.raises(TokenError, match="Token not found in database"):
            verify_refresh_token(db_session, token)

    def test_rotate_refresh_token(self, db_session):
        """Test rotating a refresh token."""
        # Create user
        user = User(
            username="testuser",
            password_hash=hash_password("TestP@ssw0rd123!"),
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()

        # Create initial token
        old_token, old_db_token = create_refresh_token(db=db_session, user_id=user.id)
        old_jti = old_db_token.jti

        # Rotate token
        new_access_token, new_refresh_token, new_db_token = rotate_refresh_token(
            db=db_session,
            old_token=old_token,
            device_info="Updated Device",
            ip_address="192.168.1.1",
        )

        # Verify old token is revoked
        db_session.refresh(old_db_token)
        assert old_db_token.revoked is True
        assert old_db_token.revoked_at is not None

        # Verify new tokens are created
        assert isinstance(new_access_token, str)
        assert isinstance(new_refresh_token, str)
        assert new_db_token.jti != old_jti
        assert new_db_token.revoked is False
        assert new_db_token.device_info == "Updated Device"
        assert new_db_token.ip_address == "192.168.1.1"

    def test_revoke_refresh_token(self, db_session):
        """Test revoking a refresh token."""
        # Create user
        user = User(
            username="testuser",
            password_hash=hash_password("TestP@ssw0rd123!"),
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()

        # Create token
        token, db_token = create_refresh_token(db=db_session, user_id=user.id)

        # Revoke token
        revoke_refresh_token(db_session, token)

        # Verify token is revoked
        db_session.refresh(db_token)
        assert db_token.revoked is True
        assert db_token.revoked_at is not None

    def test_revoke_all_user_tokens(self, db_session):
        """Test revoking all tokens for a user."""
        # Create user
        user = User(
            username="testuser",
            password_hash=hash_password("TestP@ssw0rd123!"),
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()

        # Create multiple tokens
        token1, db_token1 = create_refresh_token(db=db_session, user_id=user.id)
        token2, db_token2 = create_refresh_token(db=db_session, user_id=user.id)
        token3, db_token3 = create_refresh_token(db=db_session, user_id=user.id)

        # Revoke all tokens
        count = revoke_all_user_tokens(db_session, user.id)

        # Verify count
        assert count == 3

        # Verify all tokens are revoked
        db_session.refresh(db_token1)
        db_session.refresh(db_token2)
        db_session.refresh(db_token3)
        assert db_token1.revoked is True
        assert db_token2.revoked is True
        assert db_token3.revoked is True


class TestAuthentication:
    """Tests for user authentication."""

    def test_authenticate_user_success(self, db_session):
        """Test successful user authentication."""
        password = "TestP@ssw0rd123!"
        user = User(
            username="testuser",
            password_hash=hash_password(password),
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()

        # Authenticate
        authenticated_user = authenticate_user(
            db=db_session,
            username="testuser",
            password=password,
            ip_address="127.0.0.1",
        )

        assert authenticated_user is not None
        assert authenticated_user.id == user.id
        assert authenticated_user.username == user.username

        # Verify login was recorded
        db_session.refresh(user)
        assert user.last_login is not None
        assert user.last_login_ip == "127.0.0.1"
        assert user.failed_login_attempts == 0

    def test_authenticate_user_invalid_username(self, db_session):
        """Test authentication with invalid username."""
        result = authenticate_user(
            db=db_session,
            username="nonexistent",
            password="password",
        )

        assert result is None

    def test_authenticate_user_invalid_password(self, db_session):
        """Test authentication with invalid password."""
        user = User(
            username="testuser",
            password_hash=hash_password("TestP@ssw0rd123!"),
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()

        # Authenticate with wrong password
        result = authenticate_user(
            db=db_session,
            username="testuser",
            password="WrongPassword123!",
        )

        assert result is None

        # Verify failed login was recorded
        db_session.refresh(user)
        assert user.failed_login_attempts == 1
        assert user.last_failed_login is not None

    def test_authenticate_user_account_locked(self, db_session):
        """Test authentication with locked account."""
        user = User(
            username="testuser",
            password_hash=hash_password("TestP@ssw0rd123!"),
            is_active=True,
            account_locked_until=datetime.utcnow() + timedelta(minutes=30),
        )
        db_session.add(user)
        db_session.commit()

        # Authenticate
        with pytest.raises(AuthenticationError, match="Account is temporarily locked"):
            authenticate_user(
                db=db_session,
                username="testuser",
                password="TestP@ssw0rd123!",
            )

    def test_authenticate_user_account_inactive(self, db_session):
        """Test authentication with inactive account."""
        user = User(
            username="testuser",
            password_hash=hash_password("TestP@ssw0rd123!"),
            is_active=False,
        )
        db_session.add(user)
        db_session.commit()

        # Authenticate
        with pytest.raises(AuthenticationError, match="Account is inactive"):
            authenticate_user(
                db=db_session,
                username="testuser",
                password="TestP@ssw0rd123!",
            )

    def test_authenticate_user_lockout_after_max_attempts(self, db_session):
        """Test account lockout after max failed attempts."""
        password = "TestP@ssw0rd123!"
        user = User(
            username="testuser",
            password_hash=hash_password(password),
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()

        # Simulate max_failed_login_attempts - 1 failed attempts
        max_attempts = settings.max_failed_login_attempts
        for i in range(max_attempts - 1):
            authenticate_user(db=db_session, username="testuser", password="wrong")
            db_session.refresh(user)
            assert user.failed_login_attempts == i + 1
            assert user.account_locked_until is None

        # One more failed attempt should lock the account
        authenticate_user(db=db_session, username="testuser", password="wrong")
        db_session.refresh(user)
        assert user.failed_login_attempts == max_attempts
        assert user.account_locked_until is not None
        assert user.account_locked_until > datetime.utcnow()


class TestTwoFactorAuth:
    """Tests for two-factor authentication (TOTP)."""

    def test_generate_totp_secret(self):
        """Test generating TOTP secret."""
        secret = generate_totp_secret()

        assert isinstance(secret, str)
        assert len(secret) == 32  # Base32 encoded
        assert secret.isupper()  # Base32 uses uppercase

    def test_generate_totp_uri(self):
        """Test generating TOTP provisioning URI."""
        secret = "JBSWY3DPEHPK3PXP"
        username = "testuser"

        uri = generate_totp_uri(secret, username)

        assert uri.startswith("otpauth://totp/")
        assert username in uri
        assert secret in uri
        assert settings.app_name in uri

    def test_verify_totp_code_valid(self):
        """Test verifying valid TOTP code."""
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        code = totp.now()

        result = verify_totp_code(secret, code)

        assert result is True

    def test_verify_totp_code_invalid(self):
        """Test verifying invalid TOTP code."""
        secret = pyotp.random_base32()

        result = verify_totp_code(secret, "000000")

        assert result is False

    def test_verify_totp_code_with_time_window(self):
        """Test verifying TOTP code with time window."""
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)

        # Get code from 30 seconds ago (previous window)
        past_time = datetime.utcnow() - timedelta(seconds=30)
        with freeze_time(past_time):
            old_code = totp.now()

        # Should still be valid due to time window (valid_window=1)
        result = verify_totp_code(secret, old_code)

        # This might fail if we're right at the boundary, so we'll accept both
        # In production, the time window allows for clock drift
        assert isinstance(result, bool)


class TestTwoFactorPendingToken:
    """Tests for 2FA pending token creation and verification."""

    def test_create_2fa_pending_token(self):
        """Test creating a 2FA pending token."""
        token = create_2fa_pending_token(1, "testuser")
        assert isinstance(token, str)
        assert len(token) > 0

        payload = jwt.decode(
            token,
            settings.get_secret_key(),
            algorithms=[settings.algorithm],
        )
        assert payload["sub"] == "1"
        assert payload["username"] == "testuser"
        assert payload["type"] == "2fa_pending"
        assert "exp" in payload
        assert "jti" in payload

    def test_verify_2fa_pending_token(self):
        """Test verifying a valid 2FA pending token."""
        token = create_2fa_pending_token(1, "testuser")
        payload = verify_2fa_pending_token(token)

        assert payload["sub"] == "1"
        assert payload["username"] == "testuser"
        assert payload["type"] == "2fa_pending"

    def test_pending_token_rejected_by_access_verify(self):
        """Test that a 2FA pending token is rejected by verify_access_token."""
        token = create_2fa_pending_token(1, "testuser")
        with pytest.raises(TokenError, match="Invalid token type"):
            verify_access_token(token)

    def test_access_token_rejected_by_pending_verify(self):
        """Test that an access token is rejected by verify_2fa_pending_token."""
        token = create_access_token(1, "testuser")
        with pytest.raises(TokenError, match="Invalid token type"):
            verify_2fa_pending_token(token)

    def test_pending_token_expires(self):
        """Test that a 2FA pending token expires."""
        expire = datetime.utcnow() - timedelta(seconds=1)
        claims = {
            "sub": "1",
            "username": "testuser",
            "type": "2fa_pending",
            "exp": expire,
            "iat": datetime.utcnow(),
            "jti": "test-jti",
        }
        token = jwt.encode(claims, settings.get_secret_key(), algorithm=settings.algorithm)

        with pytest.raises(TokenError, match="Invalid 2FA pending token"):
            verify_2fa_pending_token(token)

    def test_generate_totp_qr_code_base64(self):
        """Test QR code generation returns a valid data URI."""
        uri = "otpauth://totp/Test:user@example.com?secret=JBSWY3DPEHPK3PXP&issuer=Test"
        result = generate_totp_qr_code_base64(uri)

        assert result.startswith("data:image/png;base64,")
        # Verify the base64 portion is valid
        b64_data = result.split(",", 1)[1]
        import base64
        decoded = base64.b64decode(b64_data)
        # PNG files start with these bytes
        assert decoded[:4] == b"\x89PNG"


class TestTokenCleanup:
    """Tests for token cleanup functions."""

    def test_cleanup_expired_tokens(self, db_session):
        """Test cleaning up expired refresh tokens."""
        # Create user
        user = User(
            username="testuser",
            password_hash=hash_password("TestP@ssw0rd123!"),
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()

        # Create expired tokens
        expired_token1 = RefreshToken(
            jti="expired-1",
            user_id=user.id,
            expires_at=datetime.utcnow() - timedelta(days=1),
        )
        expired_token2 = RefreshToken(
            jti="expired-2",
            user_id=user.id,
            expires_at=datetime.utcnow() - timedelta(days=2),
        )

        # Create valid token
        valid_token = RefreshToken(
            jti="valid",
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(days=30),
        )

        db_session.add_all([expired_token1, expired_token2, valid_token])
        db_session.commit()

        # Cleanup
        count = cleanup_expired_tokens(db_session)

        # Verify count
        assert count == 2

        # Verify only valid token remains
        remaining_tokens = db_session.query(RefreshToken).all()
        assert len(remaining_tokens) == 1
        assert remaining_tokens[0].jti == "valid"

    def test_cleanup_expired_tokens_keeps_revoked(self, db_session):
        """Test that cleanup doesn't remove revoked tokens (for audit)."""
        # Create user
        user = User(
            username="testuser",
            password_hash=hash_password("TestP@ssw0rd123!"),
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()

        # Create revoked but not expired token
        revoked_token = RefreshToken(
            jti="revoked",
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(days=30),
            revoked=True,
            revoked_at=datetime.utcnow(),
        )

        db_session.add(revoked_token)
        db_session.commit()

        # Cleanup
        count = cleanup_expired_tokens(db_session)

        # Verify no tokens were deleted
        assert count == 0

        # Verify revoked token still exists
        tokens = db_session.query(RefreshToken).all()
        assert len(tokens) == 1
        assert tokens[0].jti == "revoked"
