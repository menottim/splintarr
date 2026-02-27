"""
Unit tests for per-account lockout on TOTP failures (GitHub issue #14).

Verifies that the 2FA login-verify endpoint tracks failed TOTP attempts,
locks accounts after exceeding the threshold, rejects locked accounts
before TOTP verification, and resets the counter on successful TOTP.
"""

from datetime import datetime, timedelta

import pyotp
import pytest
from fastapi.testclient import TestClient

from splintarr.config import settings
from splintarr.core.auth import create_2fa_pending_token, generate_totp_secret
from splintarr.core.security import hash_password
from splintarr.models.user import User


class TestTOTPLockout:
    """Tests for per-account lockout on TOTP login failures."""

    def _create_2fa_user(self, db_session) -> tuple[User, str]:
        """Helper: create a user with 2FA enabled and return (user, totp_secret)."""
        secret = generate_totp_secret()
        user = User(
            username="testuser",
            password_hash=hash_password("TestP@ssw0rd123!"),
            is_active=True,
            totp_secret=secret,
            totp_enabled=True,
        )
        db_session.add(user)
        db_session.commit()
        return user, secret

    def _set_pending_token(self, client: TestClient, user: User) -> None:
        """Helper: set a valid 2FA pending token cookie on the test client."""
        pending_token = create_2fa_pending_token(user.id, user.username)
        client.cookies.set("2fa_pending_token", pending_token)

    def test_totp_failure_increments_failed_login_counter(
        self, client: TestClient, db_session
    ):
        """A failed TOTP attempt should increment the user's failed_login_attempts."""
        user, secret = self._create_2fa_user(db_session)
        self._set_pending_token(client, user)

        response = client.post(
            "/api/auth/2fa/login-verify",
            json={"code": "000000"},
        )

        assert response.status_code == 401
        assert "invalid" in response.json()["detail"].lower()

        db_session.refresh(user)
        assert user.failed_login_attempts == 1
        assert user.last_failed_login is not None

    def test_totp_success_resets_failed_login_counter(
        self, client: TestClient, db_session
    ):
        """A successful TOTP attempt should reset the failed login counter."""
        user, secret = self._create_2fa_user(db_session)

        # Simulate some prior TOTP failures
        user.failed_login_attempts = 3
        user.last_failed_login = datetime.utcnow()
        db_session.commit()

        self._set_pending_token(client, user)

        totp = pyotp.TOTP(secret)
        code = totp.now()

        response = client.post(
            "/api/auth/2fa/login-verify",
            json={"code": code},
        )

        assert response.status_code == 200

        db_session.refresh(user)
        assert user.failed_login_attempts == 0
        assert user.account_locked_until is None
        assert user.last_failed_login is None

    def test_account_locked_after_max_totp_failures(
        self, client: TestClient, db_session
    ):
        """Account should be locked after max_failed_login_attempts TOTP failures."""
        user, secret = self._create_2fa_user(db_session)
        max_attempts = settings.max_failed_login_attempts

        for i in range(max_attempts):
            # Need a fresh pending token for each attempt since the cookie may
            # be cleared or the client state may shift
            self._set_pending_token(client, user)

            response = client.post(
                "/api/auth/2fa/login-verify",
                json={"code": "000000"},
            )
            assert response.status_code == 401

        # Verify account is now locked
        db_session.refresh(user)
        assert user.failed_login_attempts == max_attempts
        assert user.account_locked_until is not None
        assert user.account_locked_until > datetime.utcnow()

    def test_locked_account_rejected_before_totp_check(
        self, client: TestClient, db_session
    ):
        """A locked account should be rejected before TOTP verification occurs."""
        user, secret = self._create_2fa_user(db_session)

        # Lock the account
        user.account_locked_until = datetime.utcnow() + timedelta(minutes=30)
        user.failed_login_attempts = settings.max_failed_login_attempts
        db_session.commit()

        self._set_pending_token(client, user)

        # Even with a valid TOTP code, should be rejected
        totp = pyotp.TOTP(secret)
        code = totp.now()

        response = client.post(
            "/api/auth/2fa/login-verify",
            json={"code": code},
        )

        assert response.status_code == 401
        assert "locked" in response.json()["detail"].lower()

    def test_expired_lockout_allows_totp_attempt(
        self, client: TestClient, db_session
    ):
        """An expired lockout should allow a new TOTP attempt."""
        user, secret = self._create_2fa_user(db_session)

        # Set lockout in the past (expired)
        user.account_locked_until = datetime.utcnow() - timedelta(minutes=1)
        user.failed_login_attempts = settings.max_failed_login_attempts
        db_session.commit()

        self._set_pending_token(client, user)

        totp = pyotp.TOTP(secret)
        code = totp.now()

        response = client.post(
            "/api/auth/2fa/login-verify",
            json={"code": code},
        )

        assert response.status_code == 200

        # Counter should be reset after success
        db_session.refresh(user)
        assert user.failed_login_attempts == 0
        assert user.account_locked_until is None

    def test_multiple_totp_failures_increment_counter_progressively(
        self, client: TestClient, db_session
    ):
        """Each TOTP failure should increment the counter by one."""
        user, secret = self._create_2fa_user(db_session)

        for expected_count in range(1, 4):
            self._set_pending_token(client, user)

            response = client.post(
                "/api/auth/2fa/login-verify",
                json={"code": "000000"},
            )
            assert response.status_code == 401

            db_session.refresh(user)
            assert user.failed_login_attempts == expected_count

    def test_locked_account_invalid_code_still_rejected_as_locked(
        self, client: TestClient, db_session
    ):
        """A locked account with an invalid code should get the locked error, not invalid code."""
        user, secret = self._create_2fa_user(db_session)

        # Lock the account
        user.account_locked_until = datetime.utcnow() + timedelta(minutes=30)
        user.failed_login_attempts = settings.max_failed_login_attempts
        db_session.commit()

        self._set_pending_token(client, user)

        response = client.post(
            "/api/auth/2fa/login-verify",
            json={"code": "000000"},
        )

        assert response.status_code == 401
        # Should say locked, not "invalid TOTP code"
        assert "locked" in response.json()["detail"].lower()
