"""
Unit tests for 2FA pending token replay protection.

Verifies that a 2FA pending token cannot be reused after successful verification,
preventing attackers from replaying captured tokens within the 5-minute JWT lifetime.
"""

from datetime import datetime, timedelta

import jwt
import pytest

from splintarr.config import settings
from splintarr.core.auth import (
    TokenError,
    _access_token_blacklist,
    blacklist_2fa_pending_token,
    create_2fa_pending_token,
    verify_2fa_pending_token,
)


class TestBlacklist2faPendingToken:
    """Tests for blacklist_2fa_pending_token function."""

    def setup_method(self):
        """Clear blacklist before each test."""
        _access_token_blacklist.clear()

    def test_blacklist_adds_jti(self):
        """Test that blacklisting a token adds its JTI to the blacklist."""
        token = create_2fa_pending_token(1, "testuser")

        # Decode to get JTI for assertion
        payload = jwt.decode(
            token, settings.get_secret_key(), algorithms=[settings.algorithm]
        )
        jti = payload["jti"]

        blacklist_2fa_pending_token(token)

        assert jti in _access_token_blacklist

    def test_blacklist_stores_correct_expiry(self):
        """Test that blacklisted token has correct expiry timestamp."""
        token = create_2fa_pending_token(1, "testuser")
        payload = jwt.decode(
            token, settings.get_secret_key(), algorithms=[settings.algorithm]
        )
        jti = payload["jti"]
        exp = payload["exp"]

        blacklist_2fa_pending_token(token)

        stored_expiry = _access_token_blacklist[jti]
        expected_expiry = datetime.utcfromtimestamp(exp)
        assert stored_expiry == expected_expiry

    def test_blacklist_invalid_token_does_not_raise(self):
        """Test that blacklisting an invalid token does not raise an exception."""
        # Should log a warning but not raise
        blacklist_2fa_pending_token("invalid-token-string")
        assert len(_access_token_blacklist) == 0

    def test_blacklist_expired_token_does_not_raise(self):
        """Test that blacklisting an expired token does not raise."""
        # Create an already-expired token
        expire = datetime.utcnow() - timedelta(seconds=1)
        claims = {
            "sub": "1",
            "username": "testuser",
            "type": "2fa_pending",
            "exp": expire,
            "iat": datetime.utcnow(),
            "jti": "expired-jti",
        }
        token = jwt.encode(
            claims, settings.get_secret_key(), algorithm=settings.algorithm
        )

        # Should not raise -- jwt.decode will fail but exception is caught
        blacklist_2fa_pending_token(token)


class TestVerify2faPendingTokenBlacklistCheck:
    """Tests for blacklist checking in verify_2fa_pending_token."""

    def setup_method(self):
        """Clear blacklist before each test."""
        _access_token_blacklist.clear()

    def test_blacklisted_token_is_rejected(self):
        """Test that a blacklisted 2FA pending token is rejected."""
        token = create_2fa_pending_token(1, "testuser")

        # First verification should succeed
        payload = verify_2fa_pending_token(token)
        assert payload["sub"] == "1"

        # Blacklist the token
        blacklist_2fa_pending_token(token)

        # Second verification should fail
        with pytest.raises(TokenError, match="2FA pending token has already been used"):
            verify_2fa_pending_token(token)

    def test_non_blacklisted_token_accepted(self):
        """Test that a non-blacklisted token is still accepted."""
        token = create_2fa_pending_token(1, "testuser")
        payload = verify_2fa_pending_token(token)

        assert payload["sub"] == "1"
        assert payload["type"] == "2fa_pending"

    def test_different_token_not_affected_by_blacklist(self):
        """Test that blacklisting one token does not affect another."""
        token1 = create_2fa_pending_token(1, "user1")
        token2 = create_2fa_pending_token(2, "user2")

        # Blacklist token1
        blacklist_2fa_pending_token(token1)

        # token2 should still be valid
        payload = verify_2fa_pending_token(token2)
        assert payload["sub"] == "2"

        # token1 should be rejected
        with pytest.raises(TokenError, match="2FA pending token has already been used"):
            verify_2fa_pending_token(token1)


class TestReplayProtectionEndToEnd:
    """End-to-end tests simulating the full 2FA login replay scenario.

    These tests simulate the exact sequence that happens in the login_verify_2fa
    endpoint: verify token, blacklist it, then reject replay attempts.
    """

    def setup_method(self):
        """Clear blacklist before each test."""
        _access_token_blacklist.clear()

    def test_token_used_once_then_rejected(self):
        """Simulate the login_verify_2fa flow: verify, blacklist, reject replay."""
        # Step 1: Create a 2FA pending token (simulates what /api/auth/login does)
        pending_token = create_2fa_pending_token(1, "testuser")

        # Step 2: Verify the token (simulates what login_verify_2fa does first)
        payload = verify_2fa_pending_token(pending_token)
        assert payload["sub"] == "1"
        assert payload["type"] == "2fa_pending"

        # Step 3: Blacklist it after successful TOTP verification
        # (simulates the blacklist_2fa_pending_token call in login_verify_2fa)
        blacklist_2fa_pending_token(pending_token)

        # Step 4: Attacker replays the same token -- should be rejected
        with pytest.raises(TokenError, match="2FA pending token has already been used"):
            verify_2fa_pending_token(pending_token)

    def test_multiple_replay_attempts_all_rejected(self):
        """Test that multiple replay attempts are all rejected."""
        token = create_2fa_pending_token(1, "testuser")

        # Use the token once
        verify_2fa_pending_token(token)
        blacklist_2fa_pending_token(token)

        # Multiple replay attempts should all fail
        for _ in range(5):
            with pytest.raises(TokenError, match="2FA pending token has already been used"):
                verify_2fa_pending_token(token)

    def test_fresh_token_works_after_previous_blacklisted(self):
        """Test that a fresh 2FA token works after a previous one was blacklisted."""
        # First login flow
        token1 = create_2fa_pending_token(1, "testuser")
        verify_2fa_pending_token(token1)
        blacklist_2fa_pending_token(token1)

        # Second login flow -- fresh token should work
        token2 = create_2fa_pending_token(1, "testuser")
        payload = verify_2fa_pending_token(token2)
        assert payload["sub"] == "1"

    def test_blacklist_shared_with_access_tokens(self):
        """Test that 2FA pending tokens share the blacklist with access tokens.

        This is by design -- both use _access_token_blacklist and _cleanup_blacklist
        for simplicity. JTIs are UUIDs so there's no collision risk.
        """
        token = create_2fa_pending_token(1, "testuser")
        payload = jwt.decode(
            token, settings.get_secret_key(), algorithms=[settings.algorithm]
        )
        jti = payload["jti"]

        blacklist_2fa_pending_token(token)

        # The JTI should be in the shared blacklist
        assert jti in _access_token_blacklist

    def test_blacklisted_token_cleaned_up_after_expiry(self):
        """Test that blacklisted tokens are cleaned up when expired."""
        # Create a token with very short expiry (already expired)
        past_expire = datetime.utcnow() - timedelta(seconds=10)
        claims = {
            "sub": "1",
            "username": "testuser",
            "type": "2fa_pending",
            "exp": past_expire,
            "iat": datetime.utcnow() - timedelta(minutes=6),
            "jti": "old-jti",
        }
        # Manually add to blacklist with past expiry (simulating natural expiry)
        _access_token_blacklist["old-jti"] = past_expire

        # Create and blacklist a fresh token
        fresh_token = create_2fa_pending_token(1, "testuser")
        blacklist_2fa_pending_token(fresh_token)

        # Verify the fresh token triggers cleanup of the expired entry
        # The expired "old-jti" should be cleaned up during the next verify call
        fresh_payload = jwt.decode(
            fresh_token, settings.get_secret_key(), algorithms=[settings.algorithm]
        )
        fresh_jti = fresh_payload["jti"]

        # Try to verify the fresh (blacklisted) token -- this triggers _cleanup_blacklist
        with pytest.raises(TokenError, match="2FA pending token has already been used"):
            verify_2fa_pending_token(fresh_token)

        # The expired entry should have been cleaned up, but fresh one remains
        assert "old-jti" not in _access_token_blacklist
        assert fresh_jti in _access_token_blacklist
