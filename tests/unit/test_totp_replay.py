"""
Unit tests for TOTP replay protection.

Tests that verify_totp_code() rejects replayed (previously used) codes
by tracking the time-step counter of the last accepted code.
"""

import hmac
import time
from unittest.mock import patch

import pyotp
import pytest

from splintarr.core.auth import verify_totp_code


class TestTOTPReplayProtection:
    """Tests for TOTP replay protection via counter tracking."""

    def _generate_code_at_counter(self, secret: str, counter: int) -> str:
        """Generate TOTP code for a specific time-step counter."""
        totp = pyotp.TOTP(secret)
        return totp.at(counter * 30)

    def test_valid_code_accepted_no_prior_counter(self):
        """First-ever TOTP code should be accepted when no counter is recorded."""
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        current_counter = int(time.time()) // 30
        code = totp.at(current_counter * 30)

        is_valid, used_counter = verify_totp_code(secret, code, last_used_counter=None)

        assert is_valid is True
        assert used_counter == current_counter

    def test_valid_code_accepted_with_older_counter(self):
        """Code should be accepted when its counter is greater than last used."""
        secret = pyotp.random_base32()
        current_counter = int(time.time()) // 30
        code = self._generate_code_at_counter(secret, current_counter)

        # Simulate having previously used a code from 2 steps ago
        old_counter = current_counter - 2

        is_valid, used_counter = verify_totp_code(secret, code, last_used_counter=old_counter)

        assert is_valid is True
        assert used_counter == current_counter

    def test_replay_same_code_rejected(self):
        """Same code replayed within the window should be rejected."""
        secret = pyotp.random_base32()
        current_counter = int(time.time()) // 30
        code = self._generate_code_at_counter(secret, current_counter)

        # First use succeeds
        is_valid, used_counter = verify_totp_code(secret, code, last_used_counter=None)
        assert is_valid is True
        assert used_counter == current_counter

        # Replay with same counter recorded as last_used → rejected
        is_valid2, used_counter2 = verify_totp_code(
            secret, code, last_used_counter=used_counter
        )
        assert is_valid2 is False
        assert used_counter2 is None

    def test_replay_older_counter_rejected(self):
        """Code from an older counter should be rejected if a newer counter was already used."""
        secret = pyotp.random_base32()
        current_counter = int(time.time()) // 30

        # Simulate: last used counter is the current one
        # Try to use a code from the previous period (counter - 1)
        # which is still within valid_window=1 but counter <= last_used_counter
        old_code = self._generate_code_at_counter(secret, current_counter - 1)

        is_valid, used_counter = verify_totp_code(
            secret, old_code, last_used_counter=current_counter
        )

        assert is_valid is False
        assert used_counter is None

    def test_previous_period_code_accepted_when_counter_allows(self):
        """Code from counter-1 should be accepted if last_used_counter < counter-1."""
        secret = pyotp.random_base32()
        current_counter = int(time.time()) // 30

        # Generate code for previous period (counter - 1)
        prev_code = self._generate_code_at_counter(secret, current_counter - 1)

        # last_used_counter is from 3 periods ago → counter-1 should be accepted
        is_valid, used_counter = verify_totp_code(
            secret, prev_code, last_used_counter=current_counter - 3
        )

        assert is_valid is True
        assert used_counter == current_counter - 1

    def test_next_period_code_accepted(self):
        """Code from counter+1 should be accepted (clock drift forward)."""
        secret = pyotp.random_base32()
        current_counter = int(time.time()) // 30

        # Generate code for next period (counter + 1)
        next_code = self._generate_code_at_counter(secret, current_counter + 1)

        is_valid, used_counter = verify_totp_code(
            secret, next_code, last_used_counter=current_counter - 1
        )

        assert is_valid is True
        assert used_counter == current_counter + 1

    def test_invalid_code_rejected(self):
        """Completely wrong code should be rejected."""
        secret = pyotp.random_base32()

        is_valid, used_counter = verify_totp_code(secret, "000000", last_used_counter=None)

        # Might match by coincidence, so generate a guaranteed wrong code
        totp = pyotp.TOTP(secret)
        current_counter = int(time.time()) // 30
        real_code = totp.at(current_counter * 30)
        wrong_code = str((int(real_code) + 1) % 1000000).zfill(6)

        # Make sure it doesn't match any of the 3 valid windows
        prev_code = totp.at((current_counter - 1) * 30)
        next_code = totp.at((current_counter + 1) * 30)
        if wrong_code in (prev_code, next_code, real_code):
            wrong_code = str((int(real_code) + 2) % 1000000).zfill(6)

        is_valid, used_counter = verify_totp_code(secret, wrong_code, last_used_counter=None)

        assert is_valid is False
        assert used_counter is None

    def test_counter_value_returned_matches_period(self):
        """Verify the returned counter corresponds to the correct time period."""
        secret = pyotp.random_base32()
        current_counter = int(time.time()) // 30

        # Test each valid offset
        for offset in (-1, 0, 1):
            target_counter = current_counter + offset
            code = self._generate_code_at_counter(secret, target_counter)

            is_valid, used_counter = verify_totp_code(
                secret, code, last_used_counter=current_counter - 5
            )

            assert is_valid is True
            assert used_counter == target_counter

    def test_replay_protection_sequential_logins(self):
        """Simulate sequential 2FA logins: each new code must have a higher counter."""
        secret = pyotp.random_base32()
        current_counter = int(time.time()) // 30

        # First login: use current code
        code1 = self._generate_code_at_counter(secret, current_counter)
        is_valid1, counter1 = verify_totp_code(secret, code1, last_used_counter=None)
        assert is_valid1 is True

        # Second login attempt with same code: should be rejected
        is_valid2, counter2 = verify_totp_code(secret, code1, last_used_counter=counter1)
        assert is_valid2 is False
        assert counter2 is None

        # Third login: use future code (counter + 1)
        code3 = self._generate_code_at_counter(secret, current_counter + 1)
        is_valid3, counter3 = verify_totp_code(secret, code3, last_used_counter=counter1)
        assert is_valid3 is True
        assert counter3 == current_counter + 1

    def test_return_type_is_tuple(self):
        """Verify the function returns a tuple of (bool, int | None)."""
        secret = pyotp.random_base32()
        current_counter = int(time.time()) // 30
        code = self._generate_code_at_counter(secret, current_counter)

        result = verify_totp_code(secret, code, last_used_counter=None)

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert result[1] is None or isinstance(result[1], int)

    def test_backward_compatibility_no_counter_arg(self):
        """When last_used_counter is not provided (defaults to None), codes should be accepted."""
        secret = pyotp.random_base32()
        current_counter = int(time.time()) // 30
        code = self._generate_code_at_counter(secret, current_counter)

        # Call without the last_used_counter argument (uses default None)
        is_valid, used_counter = verify_totp_code(secret, code)

        assert is_valid is True
        assert used_counter == current_counter

    def test_exception_returns_false_none(self):
        """If an exception occurs internally, return (False, None)."""
        # Pass an invalid secret that will cause pyotp to fail
        is_valid, used_counter = verify_totp_code("!!invalid!!", "123456")

        assert is_valid is False
        assert used_counter is None

    def test_constant_time_comparison_used(self):
        """Verify that hmac.compare_digest is used for constant-time comparison."""
        secret = pyotp.random_base32()
        current_counter = int(time.time()) // 30
        code = self._generate_code_at_counter(secret, current_counter)

        with patch("splintarr.core.auth.hmac.compare_digest", wraps=hmac.compare_digest) as mock_cmp:
            verify_totp_code(secret, code, last_used_counter=None)
            assert mock_cmp.called, "hmac.compare_digest should be used for constant-time comparison"
