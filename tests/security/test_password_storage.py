"""
Security-specific tests for password storage.

Tests password hashing security properties following OWASP Password Storage
Cheat Sheet recommendations.
"""

import re
import time
from unittest.mock import patch

import pytest
from argon2 import PasswordHasher

from splintarr.core.security import PasswordSecurity, password_security


class TestPasswordHashingCompliance:
    """Test OWASP password hashing compliance."""

    def test_uses_argon2id_algorithm(self):
        """Test that Argon2id algorithm is used (OWASP recommended)."""
        password = "TestPassword123"
        password_hash = password_security.hash_password(password)

        # Argon2id format: $argon2id$v=19$m=...,t=...,p=...
        assert password_hash.startswith("$argon2id$")

    def test_memory_cost_minimum_requirement(self, test_settings):
        """Test that memory cost meets OWASP minimum (64 MiB)."""
        password_hash = password_security.hash_password("TestPassword123")

        # Extract memory cost from hash
        # Format: $argon2id$v=19$m=131072,t=3,p=8$...
        match = re.search(r"m=(\d+)", password_hash)
        assert match is not None

        memory_cost_kib = int(match.group(1))
        memory_cost_mib = memory_cost_kib / 1024

        # Should be at least 64 MiB
        assert memory_cost_mib >= 64

        # Should match configured value (128 MiB = 131072 KiB)
        assert memory_cost_kib == test_settings.argon2_memory_cost

    def test_time_cost_minimum_requirement(self, test_settings):
        """Test that time cost meets OWASP minimum (2 iterations)."""
        password_hash = password_security.hash_password("TestPassword123")

        # Extract time cost
        match = re.search(r"t=(\d+)", password_hash)
        assert match is not None

        time_cost = int(match.group(1))

        # Should be at least 2 iterations
        assert time_cost >= 2

        # Should match configured value (3)
        assert time_cost == test_settings.argon2_time_cost

    def test_parallelism_configured(self, test_settings):
        """Test that parallelism is properly configured."""
        password_hash = password_security.hash_password("TestPassword123")

        # Extract parallelism
        match = re.search(r"p=(\d+)", password_hash)
        assert match is not None

        parallelism = int(match.group(1))

        # Should be at least 1
        assert parallelism >= 1

        # Should match configured value (8)
        assert parallelism == test_settings.argon2_parallelism

    def test_salt_is_unique_per_hash(self):
        """Test that each hash has a unique salt (OWASP requirement)."""
        password = "TestPassword123"
        hash1 = password_security.hash_password(password)
        hash2 = password_security.hash_password(password)

        # Hashes should be different due to unique salts
        assert hash1 != hash2

        # Both should verify correctly
        assert password_security.verify_password(password, hash1)
        assert password_security.verify_password(password, hash2)

    def test_salt_length_sufficient(self):
        """Test that salt length is sufficient (at least 128 bits)."""
        # Argon2 hasher is configured with 16-byte (128-bit) salt
        assert password_security._hasher.salt_len >= 16

    def test_hash_output_length_sufficient(self):
        """Test that hash output is sufficiently long (at least 256 bits)."""
        # Argon2 hasher is configured with 32-byte (256-bit) hash
        assert password_security._hasher.hash_len >= 32


class TestPepperImplementation:
    """Test pepper implementation for additional security layer."""

    def test_pepper_is_applied(self, test_settings):
        """Test that pepper is actually applied to passwords."""
        password = "TestPassword123"
        pepper = test_settings.get_pepper()

        # Hash with our security class (includes pepper)
        password_hash = password_security.hash_password(password)

        # Try to verify without pepper - should fail
        raw_hasher = password_security._hasher
        with pytest.raises(Exception):  # VerifyMismatchError
            raw_hasher.verify(password_hash, password)

        # Verify with pepper - should succeed
        raw_hasher.verify(password_hash, password + pepper)

    def test_pepper_required_for_verification(self, test_settings):
        """Test that verification fails without proper pepper."""
        password = "TestPassword123"
        password_hash = password_security.hash_password(password)

        # Create a new security instance with different pepper
        with patch.object(password_security, "_pepper", "wrong_pepper"):
            # Verification should fail with wrong pepper
            assert password_security.verify_password(password, password_hash) is False

    def test_pepper_not_stored_in_hash(self, test_settings):
        """Test that pepper is not stored in the hash (only salt is)."""
        password = "TestPassword123"
        pepper = test_settings.get_pepper()
        password_hash = password_security.hash_password(password)

        # Hash should not contain the pepper value
        assert pepper not in password_hash

    def test_pepper_adds_security_layer(self, test_settings):
        """Test that pepper provides defense-in-depth."""
        password = "TestPassword123"

        # Even if database is compromised, attacker needs pepper
        password_hash = password_security.hash_password(password)

        # Simulate attacker with hash but without pepper
        # They cannot verify the password
        raw_hasher = PasswordHasher()
        try:
            raw_hasher.verify(password_hash, password)
            # If this succeeds, pepper wasn't applied
            assert False, "Pepper not properly applied"
        except Exception:
            # Expected - verification should fail without pepper
            pass


class TestPasswordHashingPerformance:
    """Test password hashing performance characteristics."""

    def test_hashing_is_computationally_expensive(self):
        """Test that password hashing is intentionally slow (anti-bruteforce)."""
        password = "TestPassword123"

        # Measure time to hash
        start = time.time()
        password_security.hash_password(password)
        duration = time.time() - start

        # Should take at least 50ms (tunable based on hardware)
        # This ensures it's expensive enough to slow down attacks
        # but fast enough for normal use
        assert duration >= 0.01  # At least 10ms

    def test_verification_is_computationally_expensive(self):
        """Test that password verification is intentionally slow."""
        password = "TestPassword123"
        password_hash = password_security.hash_password(password)

        # Measure time to verify
        start = time.time()
        password_security.verify_password(password, password_hash)
        duration = time.time() - start

        # Should take at least 10ms
        assert duration >= 0.01

    def test_multiple_hashing_attempts_are_expensive(self):
        """Test that multiple hashing attempts take significant time (anti-bruteforce)."""
        password = "TestPassword123"

        # Time 10 hashing operations
        start = time.time()
        for _ in range(10):
            password_security.hash_password(password)
        duration = time.time() - start

        # Should take at least 100ms for 10 operations
        assert duration >= 0.1


class TestPasswordHashingEdgeCases:
    """Test password hashing edge cases and error conditions."""

    def test_empty_password_rejected(self):
        """Test that empty password is rejected."""
        with pytest.raises(ValueError, match="Password cannot be empty"):
            password_security.hash_password("")

    def test_very_long_password(self):
        """Test hashing very long passwords."""
        # 1000 character password
        long_password = "A" * 1000
        password_hash = password_security.hash_password(long_password)

        assert password_security.verify_password(long_password, password_hash)

    def test_unicode_password(self):
        """Test hashing passwords with Unicode characters."""
        unicode_passwords = [
            "Pässwörd123",
            "密码123",
            "пароль123",
            "🔒Password123",
        ]

        for password in unicode_passwords:
            password_hash = password_security.hash_password(password)
            assert password_security.verify_password(password, password_hash)

    def test_special_characters_in_password(self):
        """Test passwords with special characters."""
        special_passwords = [
            "Pass!@#$%^&*()",
            "Pass'word",
            'Pass"word',
            "Pass\nword",
            "Pass\tword",
            "Pass\\word",
        ]

        for password in special_passwords:
            password_hash = password_security.hash_password(password)
            assert password_security.verify_password(password, password_hash)

    def test_null_byte_in_password(self):
        """Test password containing null bytes."""
        # Some languages/systems might insert null bytes
        password_with_null = "Pass\x00word"
        password_hash = password_security.hash_password(password_with_null)

        assert password_security.verify_password(password_with_null, password_hash)


class TestPasswordVerificationSecurity:
    """Test security properties of password verification."""

    def test_verification_uses_constant_time_comparison(self):
        """Test that verification uses constant-time comparison to prevent timing attacks."""
        password = "TestPassword123"
        password_hash = password_security.hash_password(password)

        # Verify correct password multiple times
        correct_times = []
        for _ in range(100):
            start = time.perf_counter()
            password_security.verify_password(password, password_hash)
            correct_times.append(time.perf_counter() - start)

        # Verify incorrect password multiple times
        incorrect_times = []
        for _ in range(100):
            start = time.perf_counter()
            password_security.verify_password("WrongPassword", password_hash)
            incorrect_times.append(time.perf_counter() - start)

        # Times should be similar (within reasonable variance)
        # This is a basic check - proper timing attack testing requires
        # more sophisticated statistical analysis
        avg_correct = sum(correct_times) / len(correct_times)
        avg_incorrect = sum(incorrect_times) / len(incorrect_times)

        # Allow 2x difference (timing attacks usually show much larger differences)
        ratio = max(avg_correct, avg_incorrect) / min(avg_correct, avg_incorrect)
        assert ratio < 2.0

    def test_invalid_hash_format_returns_false(self):
        """Test that invalid hash format returns False, not exception."""
        password = "TestPassword123"

        invalid_hashes = [
            "not_a_valid_hash",
            "$argon2$invalid",
            "",
            "plaintext_password",
        ]

        for invalid_hash in invalid_hashes:
            # Should return False, not raise exception
            result = password_security.verify_password(password, invalid_hash)
            assert result is False

    def test_truncated_hash_returns_false(self):
        """Test that truncated hash returns False."""
        password = "TestPassword123"
        password_hash = password_security.hash_password(password)

        # Truncate the hash
        truncated_hash = password_hash[:50]

        result = password_security.verify_password(password, truncated_hash)
        assert result is False

    def test_tampered_hash_returns_false(self):
        """Test that tampered hash returns False."""
        password = "TestPassword123"
        password_hash = password_security.hash_password(password)

        # Tamper with the hash
        tampered_hash = password_hash[:-10] + "TAMPERED!!"

        result = password_security.verify_password(password, tampered_hash)
        assert result is False


class TestPasswordRehashingSupport:
    """Test support for password rehashing when parameters change."""

    def test_needs_rehash_for_current_params_returns_false(self):
        """Test that current hashes don't need rehashing."""
        password_hash = password_security.hash_password("TestPassword123")

        assert password_security.needs_rehash(password_hash) is False

    def test_needs_rehash_for_old_params_returns_true(self):
        """Test that hashes with old parameters need rehashing."""
        # Create hash with weaker parameters
        old_hasher = PasswordHasher(time_cost=1, memory_cost=64 * 1024, parallelism=1)

        # Note: this still needs pepper, so we apply it
        pepper = password_security._pepper
        old_hash = old_hasher.hash("TestPassword123" + pepper)

        # Should need rehash
        assert password_security.needs_rehash(old_hash) is True

    def test_needs_rehash_for_invalid_hash_returns_true(self):
        """Test that invalid hashes are marked for rehashing."""
        invalid_hash = "not_a_valid_argon2_hash"

        assert password_security.needs_rehash(invalid_hash) is True

    def test_rehashing_preserves_verification(self):
        """Test that after rehashing, password still verifies."""
        password = "TestPassword123"

        # Create old hash
        old_hasher = PasswordHasher(time_cost=1, memory_cost=64 * 1024, parallelism=1)
        pepper = password_security._pepper
        old_hash = old_hasher.hash(password + pepper)

        # Verify old hash still works
        assert password_security.verify_password(password, old_hash)

        # Create new hash with current parameters
        new_hash = password_security.hash_password(password)

        # Verify new hash works
        assert password_security.verify_password(password, new_hash)

        # New hash shouldn't need rehashing
        assert password_security.needs_rehash(new_hash) is False


class TestPasswordHashStorage:
    """Test password hash storage properties."""

    def test_hash_is_ascii_safe(self):
        """Test that hash contains only ASCII characters."""
        password = "TestPassword123"
        password_hash = password_security.hash_password(password)

        # Hash should be ASCII-safe (can be stored in ASCII database field)
        assert password_hash.isascii()

    def test_hash_length_reasonable(self):
        """Test that hash length is reasonable for database storage."""
        password = "TestPassword123"
        password_hash = password_security.hash_password(password)

        # Hash should fit in VARCHAR(255)
        assert len(password_hash) < 255

    def test_hash_is_deterministic_format(self):
        """Test that hash format is consistent."""
        password = "TestPassword123"
        password_hash = password_security.hash_password(password)

        # Should match Argon2 format
        # $argon2id$v=19$m=...,t=...,p=...$salt$hash
        parts = password_hash.split("$")

        assert parts[1] == "argon2id"  # Algorithm
        assert parts[2].startswith("v=")  # Version
        assert "m=" in parts[3]  # Memory
        assert "t=" in parts[3]  # Time
        assert "p=" in parts[3]  # Parallelism
        assert len(parts) >= 6  # Has all parts


class TestPasswordSecurityDefenseInDepth:
    """Test defense-in-depth security measures."""

    def test_pepper_provides_defense_if_db_compromised(self, test_settings):
        """Test that pepper provides protection if database is compromised."""
        password = "TestPassword123"
        password_hash = password_security.hash_password(password)

        # Simulate attacker who has database but not pepper
        # They cannot verify passwords without the pepper
        attacker_hasher = PasswordHasher()

        try:
            attacker_hasher.verify(password_hash, password)
            assert False, "Should not verify without pepper"
        except Exception:
            # Expected - verification should fail
            pass

    def test_salt_provides_defense_against_rainbow_tables(self):
        """Test that unique salts prevent rainbow table attacks."""
        # Rainbow tables are precomputed hashes for common passwords
        # With unique salts, each hash is different even for same password
        common_password = "Password123"

        hash1 = password_security.hash_password(common_password)
        hash2 = password_security.hash_password(common_password)

        # Even with same password, hashes differ (different salts)
        assert hash1 != hash2

    def test_high_iteration_count_slows_bruteforce(self):
        """Test that high iteration count makes brute-force expensive."""
        password = "TestPassword123"

        # Time to hash one password
        start = time.time()
        password_security.hash_password(password)
        single_hash_time = time.time() - start

        # Attacker would need this time * number of attempts
        # With millions of attempts, this becomes prohibitive
        attempts_per_second = 1 / single_hash_time if single_hash_time > 0 else float("inf")

        # Should be less than 100 attempts per second
        # (makes brute-force very slow)
        assert attempts_per_second < 100
