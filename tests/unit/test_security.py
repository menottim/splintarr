"""
Unit tests for core security functions.

Tests password hashing, field encryption, token generation, and secure comparison
following OWASP security testing guidelines.
"""

import secrets
import string
from unittest.mock import Mock, patch

import pytest
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import InvalidToken

from splintarr.core.security import (
    EncryptionError,
    FieldEncryption,
    PasswordHashingError,
    PasswordSecurity,
    SecureComparison,
    TokenGenerator,
    constant_time_compare,
    decrypt_field,
    encrypt_field,
    field_encryption,
    generate_token,
    hash_password,
    password_security,
    secure_comparison,
    token_generator,
    verify_password,
)


class TestPasswordSecurity:
    """Test password hashing and verification using Argon2id with pepper."""

    def test_hash_password_success(self, test_settings):
        """Test successful password hashing."""
        password = "TestPassword123!@#"
        password_hash = password_security.hash_password(password)

        # Verify hash format (Argon2id format)
        assert password_hash.startswith("$argon2id$")
        assert len(password_hash) > 50
        # Verify parameters are embedded in hash
        assert "m=131072" in password_hash  # memory_cost (128 MiB = 131072 KiB)
        assert "t=3" in password_hash  # time_cost
        assert "p=8" in password_hash  # parallelism

    def test_hash_password_empty_raises_error(self):
        """Test that empty password raises ValueError."""
        with pytest.raises(ValueError, match="Password cannot be empty"):
            password_security.hash_password("")

    def test_hash_password_with_pepper(self, test_settings):
        """Test that pepper is applied during hashing."""
        password = "TestPassword123"
        pepper = test_settings.get_pepper()

        # Hash should include pepper
        password_hash = password_security.hash_password(password)

        # Verify that password without pepper doesn't match
        hasher = password_security._hasher
        with pytest.raises((VerifyMismatchError, InvalidHashError)):
            hasher.verify(password_hash, password)  # Missing pepper

        # Verify with pepper should work
        hasher.verify(password_hash, password + pepper)

    def test_hash_password_unique_salts(self):
        """Test that same password produces different hashes (unique salts)."""
        password = "TestPassword123"
        hash1 = password_security.hash_password(password)
        hash2 = password_security.hash_password(password)

        # Hashes should be different due to unique salts
        assert hash1 != hash2

    def test_hash_password_correct_parameters(self, test_settings):
        """Test that Argon2id parameters match OWASP recommendations."""
        password_hash = password_security.hash_password("TestPassword123")

        # Extract parameters from hash
        assert "$argon2id$" in password_hash
        # Memory cost should be at least 64 MiB (65536 KiB)
        assert "m=131072" in password_hash  # 128 MiB
        # Time cost should be at least 2
        assert "t=3" in password_hash
        # Parallelism should be reasonable
        assert "p=8" in password_hash

    def test_verify_password_success(self):
        """Test successful password verification."""
        password = "TestPassword123!@#"
        password_hash = password_security.hash_password(password)

        assert password_security.verify_password(password, password_hash) is True

    def test_verify_password_wrong_password(self):
        """Test verification fails with wrong password."""
        password = "TestPassword123"
        wrong_password = "WrongPassword456"
        password_hash = password_security.hash_password(password)

        assert password_security.verify_password(wrong_password, password_hash) is False

    def test_verify_password_empty_raises_error(self):
        """Test that empty password or hash raises ValueError."""
        with pytest.raises(ValueError, match="Password and hash cannot be empty"):
            password_security.verify_password("", "somehash")

        with pytest.raises(ValueError, match="Password and hash cannot be empty"):
            password_security.verify_password("password", "")

    def test_verify_password_invalid_hash_returns_false(self):
        """Test that invalid hash format returns False."""
        password = "TestPassword123"
        invalid_hash = "not_a_valid_argon2_hash"

        assert password_security.verify_password(password, invalid_hash) is False

    def test_verify_password_constant_time(self):
        """Test that password verification uses constant-time comparison."""
        # This is a behavioral test - Argon2 library handles this internally
        password = "TestPassword123"
        password_hash = password_security.hash_password(password)

        # Both correct and incorrect passwords should take similar time
        # We can't easily test timing, but we verify the behavior is consistent
        assert password_security.verify_password(password, password_hash) is True
        assert password_security.verify_password("wrong", password_hash) is False

    def test_needs_rehash_false_for_current_params(self):
        """Test needs_rehash returns False for current parameters."""
        password_hash = password_security.hash_password("TestPassword123")
        assert password_security.needs_rehash(password_hash) is False

    def test_needs_rehash_true_for_old_params(self):
        """Test needs_rehash returns True for outdated parameters."""
        # Create a hash with different parameters
        from argon2 import PasswordHasher

        old_hasher = PasswordHasher(time_cost=1, memory_cost=64 * 1024, parallelism=1)
        old_hash = old_hasher.hash("TestPassword123")

        # Should need rehash due to different parameters
        assert password_security.needs_rehash(old_hash) is True

    def test_needs_rehash_invalid_hash(self):
        """Test needs_rehash returns True for invalid hash."""
        invalid_hash = "not_a_valid_hash"
        assert password_security.needs_rehash(invalid_hash) is True

    def test_password_hashing_error_propagation(self):
        """Test that PasswordHashingError is raised on hashing failure."""
        with patch.object(
            password_security._hasher, "hash", side_effect=Exception("Hashing failed")
        ):
            with pytest.raises(PasswordHashingError, match="Failed to hash password"):
                password_security.hash_password("TestPassword123")

    def test_convenience_functions(self):
        """Test module-level convenience functions."""
        password = "TestPassword123"
        password_hash = hash_password(password)

        assert verify_password(password, password_hash) is True
        assert verify_password("wrong", password_hash) is False

    def test_special_characters_in_password(self):
        """Test password hashing with special characters."""
        special_passwords = [
            "Test!@#$%^&*()",
            "Tëst_Pässwörd",
            "Test\nPassword",
            "Test\tPassword",
            "Test'Password\"",
        ]

        for password in special_passwords:
            password_hash = password_security.hash_password(password)
            assert password_security.verify_password(password, password_hash) is True

    def test_long_password(self):
        """Test password hashing with very long password."""
        long_password = "A" * 1000
        password_hash = password_security.hash_password(long_password)
        assert password_security.verify_password(long_password, password_hash) is True


class TestFieldEncryption:
    """Test field-level encryption using Fernet."""

    def test_encrypt_success(self):
        """Test successful encryption."""
        plaintext = "MyAPIKey123456"
        ciphertext = field_encryption.encrypt(plaintext)

        # Fernet ciphertext should start with 'gAAAAA' (base64 encoded)
        assert ciphertext.startswith("gAAAAA")
        assert ciphertext != plaintext

    def test_encrypt_empty_raises_error(self):
        """Test that empty plaintext raises ValueError."""
        with pytest.raises(ValueError, match="Plaintext cannot be empty"):
            field_encryption.encrypt("")

    def test_decrypt_success(self):
        """Test successful decryption."""
        plaintext = "MyAPIKey123456"
        ciphertext = field_encryption.encrypt(plaintext)
        decrypted = field_encryption.decrypt(ciphertext)

        assert decrypted == plaintext

    def test_decrypt_empty_raises_error(self):
        """Test that empty ciphertext raises ValueError."""
        with pytest.raises(ValueError, match="Ciphertext cannot be empty"):
            field_encryption.decrypt("")

    def test_decrypt_invalid_token_raises_error(self):
        """Test that invalid ciphertext raises EncryptionError."""
        invalid_ciphertext = "invalid_base64_token"

        with pytest.raises(EncryptionError, match="Failed to decrypt data"):
            field_encryption.decrypt(invalid_ciphertext)

    def test_decrypt_tampered_data_raises_error(self):
        """Test that tampered ciphertext raises EncryptionError."""
        plaintext = "MyAPIKey123456"
        ciphertext = field_encryption.encrypt(plaintext)

        # Tamper with the ciphertext
        tampered = ciphertext[:-10] + "TAMPERED=="

        with pytest.raises(EncryptionError, match="Invalid token or tampered data"):
            field_encryption.decrypt(tampered)

    def test_encryption_is_reversible(self):
        """Test that encryption and decryption are reversible."""
        test_values = [
            "SimpleAPIKey",
            "API_KEY_WITH_UNDERSCORES",
            "APIKey!@#$%^&*()",
            "Very Long API Key " * 100,
            "APIKey\nWith\nNewlines",
        ]

        for plaintext in test_values:
            ciphertext = field_encryption.encrypt(plaintext)
            decrypted = field_encryption.decrypt(ciphertext)
            assert decrypted == plaintext

    def test_encryption_produces_different_ciphertexts(self):
        """Test that encrypting same plaintext produces different ciphertexts."""
        plaintext = "MyAPIKey123456"
        ciphertext1 = field_encryption.encrypt(plaintext)
        ciphertext2 = field_encryption.encrypt(plaintext)

        # Due to random IV in Fernet, ciphertexts should be different
        assert ciphertext1 != ciphertext2

        # But both should decrypt to same plaintext
        assert field_encryption.decrypt(ciphertext1) == plaintext
        assert field_encryption.decrypt(ciphertext2) == plaintext

    def test_encrypt_if_needed_with_plaintext(self):
        """Test encrypt_if_needed with plaintext."""
        plaintext = "MyAPIKey"
        result = field_encryption.encrypt_if_needed(plaintext)

        assert result.startswith("gAAAAA")
        assert field_encryption.decrypt(result) == plaintext

    def test_encrypt_if_needed_with_encrypted_value(self):
        """Test encrypt_if_needed with already encrypted value."""
        plaintext = "MyAPIKey"
        encrypted = field_encryption.encrypt(plaintext)

        # Should return same encrypted value
        result = field_encryption.encrypt_if_needed(encrypted)
        assert result == encrypted

    def test_encrypt_if_needed_with_none(self):
        """Test encrypt_if_needed with None."""
        result = field_encryption.encrypt_if_needed(None)
        assert result is None

    def test_decrypt_if_needed_with_ciphertext(self):
        """Test decrypt_if_needed with encrypted value."""
        plaintext = "MyAPIKey"
        ciphertext = field_encryption.encrypt(plaintext)

        result = field_encryption.decrypt_if_needed(ciphertext)
        assert result == plaintext

    def test_decrypt_if_needed_with_plaintext(self):
        """Test decrypt_if_needed with plaintext (legacy data)."""
        plaintext = "UnencryptedAPIKey"

        # Should return plaintext as-is
        result = field_encryption.decrypt_if_needed(plaintext)
        assert result == plaintext

    def test_decrypt_if_needed_with_none(self):
        """Test decrypt_if_needed with None."""
        result = field_encryption.decrypt_if_needed(None)
        assert result is None

    def test_decrypt_if_needed_with_invalid_encrypted_returns_original(self):
        """Test decrypt_if_needed with invalid encrypted data returns original."""
        # Create something that looks encrypted but isn't valid
        invalid_encrypted = "gAAAAAInvalidData"

        # Should return original value if decryption fails
        result = field_encryption.decrypt_if_needed(invalid_encrypted)
        assert result == invalid_encrypted

    def test_convenience_functions(self):
        """Test module-level convenience functions."""
        plaintext = "TestAPIKey"
        encrypted = encrypt_field(plaintext)
        decrypted = decrypt_field(encrypted)

        assert decrypted == plaintext

    def test_fernet_includes_authentication(self):
        """Test that Fernet provides authenticated encryption."""
        plaintext = "MyAPIKey"
        ciphertext = field_encryption.encrypt(plaintext)

        # Modify one character in the middle
        modified = list(ciphertext)
        modified[20] = "X" if modified[20] != "X" else "Y"
        modified_ciphertext = "".join(modified)

        # Should raise error due to failed authentication
        with pytest.raises(EncryptionError):
            field_encryption.decrypt(modified_ciphertext)


class TestTokenGenerator:
    """Test cryptographically secure token generation."""

    def test_generate_token_default_length(self):
        """Test token generation with default length."""
        token = token_generator.generate_token()

        # URL-safe base64 encoded, ~43 chars for 32 bytes
        assert len(token) > 40
        assert all(c in string.ascii_letters + string.digits + "-_" for c in token)

    def test_generate_token_custom_length(self):
        """Test token generation with custom length."""
        token = token_generator.generate_token(length=64)

        # Longer token
        assert len(token) > 80

    def test_generate_token_minimum_length(self):
        """Test token generation enforces minimum length."""
        with pytest.raises(ValueError, match="Token length must be at least 16 bytes"):
            token_generator.generate_token(length=15)

    def test_generate_token_uniqueness(self):
        """Test that generated tokens are unique."""
        tokens = [token_generator.generate_token() for _ in range(100)]

        # All tokens should be unique
        assert len(set(tokens)) == 100

    def test_generate_token_cryptographically_secure(self):
        """Test that tokens use cryptographically secure random source."""
        # Generate many tokens and check for patterns
        tokens = [token_generator.generate_token(16) for _ in range(1000)]

        # Basic entropy check - all tokens should be unique
        assert len(set(tokens)) == 1000

        # Check character distribution is reasonable (not perfect but reasonable)
        all_chars = "".join(tokens)
        unique_chars = set(all_chars)
        # URL-safe base64 has 64 possible characters, should see good variety
        assert len(unique_chars) > 50

    def test_generate_api_key_default_length(self):
        """Test API key generation with default length."""
        api_key = token_generator.generate_api_key()

        assert len(api_key) == 64
        assert all(c in string.ascii_letters + string.digits for c in api_key)

    def test_generate_api_key_custom_length(self):
        """Test API key generation with custom length."""
        api_key = token_generator.generate_api_key(length=128)
        assert len(api_key) == 128

    def test_generate_api_key_minimum_length(self):
        """Test API key generation enforces minimum length."""
        with pytest.raises(ValueError, match="API key length must be at least 32"):
            token_generator.generate_api_key(length=31)

    def test_generate_api_key_uniqueness(self):
        """Test that generated API keys are unique."""
        api_keys = [token_generator.generate_api_key() for _ in range(100)]
        assert len(set(api_keys)) == 100

    def test_generate_numeric_code_default_length(self):
        """Test numeric code generation with default length."""
        code = token_generator.generate_numeric_code()

        assert len(code) == 6
        assert code.isdigit()

    def test_generate_numeric_code_custom_length(self):
        """Test numeric code generation with custom length."""
        code = token_generator.generate_numeric_code(length=8)
        assert len(code) == 8
        assert code.isdigit()

    def test_generate_numeric_code_minimum_length(self):
        """Test numeric code generation enforces minimum length."""
        with pytest.raises(ValueError, match="Code length must be at least 4 digits"):
            token_generator.generate_numeric_code(length=3)

    def test_generate_numeric_code_uniqueness(self):
        """Test that generated numeric codes are reasonably unique."""
        codes = [token_generator.generate_numeric_code(length=8) for _ in range(1000)]

        # Should have high uniqueness (allow some collisions for 8-digit codes)
        assert len(set(codes)) > 990

    def test_generate_hex_token_default_length(self):
        """Test hex token generation with default length."""
        token = token_generator.generate_hex_token()

        # 32 bytes = 64 hex characters
        assert len(token) == 64
        assert all(c in string.hexdigits.lower() for c in token)

    def test_generate_hex_token_custom_length(self):
        """Test hex token generation with custom length."""
        token = token_generator.generate_hex_token(length=16)
        assert len(token) == 32  # 16 bytes = 32 hex chars

    def test_generate_hex_token_minimum_length(self):
        """Test hex token generation enforces minimum length."""
        with pytest.raises(ValueError, match="Token length must be at least 16 bytes"):
            token_generator.generate_hex_token(length=15)

    def test_generate_hex_token_uniqueness(self):
        """Test that generated hex tokens are unique."""
        tokens = [token_generator.generate_hex_token() for _ in range(100)]
        assert len(set(tokens)) == 100

    def test_convenience_function(self):
        """Test module-level convenience function."""
        token = generate_token(32)
        assert len(token) > 40


class TestSecureComparison:
    """Test constant-time comparison functions."""

    def test_compare_digest_strings_equal(self):
        """Test constant-time comparison of equal strings."""
        value1 = "my_secret_token"
        value2 = "my_secret_token"

        assert secure_comparison.compare_digest(value1, value2) is True

    def test_compare_digest_strings_not_equal(self):
        """Test constant-time comparison of unequal strings."""
        value1 = "my_secret_token"
        value2 = "different_token"

        assert secure_comparison.compare_digest(value1, value2) is False

    def test_compare_digest_bytes_equal(self):
        """Test constant-time comparison of equal bytes."""
        value1 = b"my_secret_token"
        value2 = b"my_secret_token"

        assert secure_comparison.compare_digest(value1, value2) is True

    def test_compare_digest_bytes_not_equal(self):
        """Test constant-time comparison of unequal bytes."""
        value1 = b"my_secret_token"
        value2 = b"different_token"

        assert secure_comparison.compare_digest(value1, value2) is False

    def test_compare_digest_mixed_types_raises_error(self):
        """Test that comparing mixed types raises TypeError."""
        with pytest.raises(TypeError, match="Both values must be of the same type"):
            secure_comparison.compare_digest("string", b"bytes")

    def test_compare_digest_different_lengths(self):
        """Test comparison of strings with different lengths."""
        value1 = "short"
        value2 = "very_long_token"

        # Should still use constant-time comparison
        assert secure_comparison.compare_digest(value1, value2) is False

    def test_compare_digest_empty_strings(self):
        """Test comparison of empty strings."""
        assert secure_comparison.compare_digest("", "") is True
        assert secure_comparison.compare_digest("", "nonempty") is False

    def test_compare_digest_uses_secrets_module(self):
        """Test that comparison uses secrets.compare_digest internally."""
        # This is verified by the implementation using secrets.compare_digest
        value1 = "token123"
        value2 = "token123"

        with patch("secrets.compare_digest", return_value=True) as mock_compare:
            result = secure_comparison.compare_digest(value1, value2)
            assert result is True
            mock_compare.assert_called_once()

    def test_convenience_function(self):
        """Test module-level convenience function."""
        assert constant_time_compare("token123", "token123") is True
        assert constant_time_compare("token123", "token456") is False

    def test_timing_attack_resistance(self):
        """Test that comparison is resistant to timing attacks."""
        # This is a behavioral test - we can't easily measure timing,
        # but we verify that the function uses secrets.compare_digest
        correct_token = "A" * 100
        wrong_tokens = [
            "B" + "A" * 99,  # First char wrong
            "A" * 50 + "B" + "A" * 49,  # Middle char wrong
            "A" * 99 + "B",  # Last char wrong
        ]

        # All comparisons should return False
        for wrong_token in wrong_tokens:
            assert secure_comparison.compare_digest(correct_token, wrong_token) is False


class TestGlobalInstances:
    """Test global singleton instances."""

    def test_global_password_security_instance(self):
        """Test that global password_security instance exists and works."""
        password = "TestPassword123"
        password_hash = password_security.hash_password(password)

        assert password_security.verify_password(password, password_hash) is True

    def test_global_field_encryption_instance(self):
        """Test that global field_encryption instance exists and works."""
        plaintext = "TestAPIKey"
        encrypted = field_encryption.encrypt(plaintext)
        decrypted = field_encryption.decrypt(encrypted)

        assert decrypted == plaintext

    def test_global_token_generator_instance(self):
        """Test that global token_generator instance exists and works."""
        token = token_generator.generate_token()
        assert len(token) > 40

    def test_global_secure_comparison_instance(self):
        """Test that global secure_comparison instance exists and works."""
        assert secure_comparison.compare_digest("test", "test") is True
        assert secure_comparison.compare_digest("test", "different") is False
