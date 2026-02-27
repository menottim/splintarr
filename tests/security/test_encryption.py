"""
Security-specific tests for field encryption.

Tests encryption security properties following OWASP cryptographic storage guidelines.
"""

import base64
import re
import time
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet, InvalidToken

from splintarr.core.security import EncryptionError, FieldEncryption, field_encryption


class TestEncryptionCompliance:
    """Test OWASP cryptographic storage compliance."""

    def test_uses_authenticated_encryption(self):
        """Test that Fernet provides authenticated encryption (AEAD)."""
        # Fernet uses AES-128-CBC with HMAC-SHA256 for authentication
        plaintext = "SensitiveAPIKey123"
        ciphertext = field_encryption.encrypt(plaintext)

        # Tamper with ciphertext
        tampered = list(ciphertext)
        tampered[20] = "X" if tampered[20] != "X" else "Y"
        tampered_ciphertext = "".join(tampered)

        # Should detect tampering
        with pytest.raises(EncryptionError, match="Invalid token or tampered data"):
            field_encryption.decrypt(tampered_ciphertext)

    def test_encryption_includes_timestamp(self):
        """Test that Fernet includes timestamp for freshness verification."""
        plaintext = "APIKey123"
        ciphertext = field_encryption.encrypt(plaintext)

        # Fernet tokens include timestamp (version byte + timestamp + IV + ciphertext + HMAC)
        # Decode to verify structure
        decoded = base64.urlsafe_b64decode(ciphertext.encode())

        # First byte should be version (0x80 for Fernet)
        assert decoded[0] == 0x80

        # Next 8 bytes are timestamp
        timestamp_bytes = decoded[1:9]
        assert len(timestamp_bytes) == 8

    def test_uses_strong_encryption_algorithm(self):
        """Test that AES encryption is used (OWASP recommended)."""
        # Fernet uses AES-128-CBC
        # The cipher is created in FieldEncryption.__init__
        # We verify by checking that decryption works correctly

        plaintext = "APIKey123"
        ciphertext = field_encryption.encrypt(plaintext)
        decrypted = field_encryption.decrypt(ciphertext)

        assert decrypted == plaintext

    def test_uses_hmac_for_authentication(self):
        """Test that HMAC is used for message authentication."""
        plaintext = "APIKey123"
        ciphertext = field_encryption.encrypt(plaintext)

        # Fernet format: version (1) + timestamp (8) + IV (16) + ciphertext (variable) + HMAC (32)
        decoded = base64.urlsafe_b64decode(ciphertext.encode())

        # HMAC should be last 32 bytes
        hmac = decoded[-32:]
        assert len(hmac) == 32

        # Changing any byte should invalidate HMAC
        tampered = bytearray(decoded)
        tampered[10] ^= 0x01  # Flip one bit
        tampered_b64 = base64.urlsafe_b64encode(bytes(tampered)).decode()

        with pytest.raises(EncryptionError):
            field_encryption.decrypt(tampered_b64)


class TestEncryptionKeyManagement:
    """Test encryption key management security."""

    def test_encryption_key_derived_from_secret(self, test_settings):
        """Test that encryption key is derived from application secret."""
        # FieldEncryption derives key from secret_key
        # Verify by checking key length and format
        key_bytes = test_settings.get_secret_key().encode()[:32].ljust(32, b"0")
        fernet_key = base64.urlsafe_b64encode(key_bytes)

        # Should be valid Fernet key
        cipher = Fernet(fernet_key)
        assert cipher is not None

    def test_encryption_key_length_sufficient(self):
        """Test that encryption key length is sufficient (256 bits for Fernet)."""
        # Fernet requires 32-byte (256-bit) base64-encoded key
        # Key is derived in __init__
        plaintext = "Test"
        ciphertext = field_encryption.encrypt(plaintext)

        # If key was wrong length, encryption would fail
        assert ciphertext is not None

    def test_different_secrets_produce_different_ciphertexts(self, test_settings):
        """Test that different secret keys produce different ciphertexts."""
        plaintext = "APIKey123"

        # Encrypt with current key
        ciphertext1 = field_encryption.encrypt(plaintext)

        # Create new encryption instance with different key
        with patch.object(test_settings, "get_secret_key", return_value="different_secret_key_32_bytes!"):
            encryption2 = FieldEncryption()
            ciphertext2 = encryption2.encrypt(plaintext)

        # Ciphertexts should be different
        assert ciphertext1 != ciphertext2

    def test_cannot_decrypt_with_wrong_key(self, test_settings):
        """Test that ciphertext cannot be decrypted with wrong key."""
        plaintext = "APIKey123"
        ciphertext = field_encryption.encrypt(plaintext)

        # Try to decrypt with different key
        with patch.object(test_settings, "get_secret_key", return_value="wrong_secret_key_32_bytes!!!!!"):
            encryption2 = FieldEncryption()

            with pytest.raises(EncryptionError):
                encryption2.decrypt(ciphertext)


class TestEncryptionRandomness:
    """Test encryption randomness and IV generation."""

    def test_same_plaintext_produces_different_ciphertexts(self):
        """Test that encrypting same plaintext produces different ciphertexts (due to IV)."""
        plaintext = "APIKey123"

        ciphertext1 = field_encryption.encrypt(plaintext)
        ciphertext2 = field_encryption.encrypt(plaintext)

        # Should be different due to random IV
        assert ciphertext1 != ciphertext2

        # But both should decrypt to same plaintext
        assert field_encryption.decrypt(ciphertext1) == plaintext
        assert field_encryption.decrypt(ciphertext2) == plaintext

    def test_iv_is_unique_per_encryption(self):
        """Test that each encryption uses a unique IV."""
        plaintext = "APIKey123"

        # Generate multiple ciphertexts
        ciphertexts = [field_encryption.encrypt(plaintext) for _ in range(100)]

        # Extract IVs from ciphertexts
        # Fernet format: version (1) + timestamp (8) + IV (16) + ciphertext + HMAC (32)
        ivs = []
        for ciphertext in ciphertexts:
            decoded = base64.urlsafe_b64decode(ciphertext.encode())
            iv = decoded[9:25]  # IV is bytes 9-24
            ivs.append(iv)

        # All IVs should be unique
        unique_ivs = set(ivs)
        assert len(unique_ivs) == len(ivs)

    def test_iv_length_correct(self):
        """Test that IV length is correct (128 bits for AES)."""
        plaintext = "APIKey123"
        ciphertext = field_encryption.encrypt(plaintext)

        # Extract IV
        decoded = base64.urlsafe_b64decode(ciphertext.encode())
        iv = decoded[9:25]

        # Should be 16 bytes (128 bits)
        assert len(iv) == 16


class TestEncryptionEdgeCases:
    """Test encryption edge cases and error conditions."""

    def test_empty_plaintext_rejected(self):
        """Test that empty plaintext is rejected."""
        with pytest.raises(ValueError, match="Plaintext cannot be empty"):
            field_encryption.encrypt("")

    def test_empty_ciphertext_rejected(self):
        """Test that empty ciphertext is rejected."""
        with pytest.raises(ValueError, match="Ciphertext cannot be empty"):
            field_encryption.decrypt("")

    def test_very_long_plaintext(self):
        """Test encrypting very long plaintext."""
        # 10KB plaintext
        long_plaintext = "A" * 10000
        ciphertext = field_encryption.encrypt(long_plaintext)
        decrypted = field_encryption.decrypt(ciphertext)

        assert decrypted == long_plaintext

    def test_unicode_plaintext(self):
        """Test encrypting Unicode data."""
        unicode_texts = [
            "APIKey-密码",
            "Key-مفتاح",
            "Ключ-123",
            "🔑-Key",
        ]

        for plaintext in unicode_texts:
            ciphertext = field_encryption.encrypt(plaintext)
            decrypted = field_encryption.decrypt(ciphertext)
            assert decrypted == plaintext

    def test_special_characters_in_plaintext(self):
        """Test encrypting special characters."""
        special_texts = [
            "Key!@#$%^&*()",
            "Key\nWith\nNewlines",
            "Key\tWith\tTabs",
            "Key'With\"Quotes",
            "Key\\With\\Backslashes",
        ]

        for plaintext in special_texts:
            ciphertext = field_encryption.encrypt(plaintext)
            decrypted = field_encryption.decrypt(ciphertext)
            assert decrypted == plaintext

    def test_binary_data_handling(self):
        """Test that encryption handles binary data correctly."""
        # Fernet expects bytes, our wrapper handles string encoding
        plaintext = "Binary\x00Data\xff"
        ciphertext = field_encryption.encrypt(plaintext)
        decrypted = field_encryption.decrypt(ciphertext)

        assert decrypted == plaintext


class TestEncryptionTamperDetection:
    """Test encryption tamper detection capabilities."""

    def test_detects_modified_ciphertext(self):
        """Test that modified ciphertext is detected."""
        plaintext = "APIKey123"
        ciphertext = field_encryption.encrypt(plaintext)

        # Modify middle of ciphertext
        modified = list(ciphertext)
        modified[len(ciphertext) // 2] = "X"
        modified_ciphertext = "".join(modified)

        with pytest.raises(EncryptionError):
            field_encryption.decrypt(modified_ciphertext)

    def test_detects_truncated_ciphertext(self):
        """Test that truncated ciphertext is detected."""
        plaintext = "APIKey123"
        ciphertext = field_encryption.encrypt(plaintext)

        # Truncate ciphertext
        truncated = ciphertext[:-10]

        with pytest.raises(EncryptionError):
            field_encryption.decrypt(truncated)

    def test_detects_extended_ciphertext(self):
        """Test that extended ciphertext is detected."""
        plaintext = "APIKey123"
        ciphertext = field_encryption.encrypt(plaintext)

        # Extend ciphertext
        extended = ciphertext + "EXTRA"

        with pytest.raises(EncryptionError):
            field_encryption.decrypt(extended)

    def test_detects_tampered_hmac(self):
        """Test that tampered HMAC is detected."""
        plaintext = "APIKey123"
        ciphertext = field_encryption.encrypt(plaintext)

        # Tamper with HMAC (last 32 bytes of decoded token)
        decoded = base64.urlsafe_b64decode(ciphertext.encode())
        tampered = bytearray(decoded)
        tampered[-1] ^= 0x01  # Flip one bit in HMAC
        tampered_b64 = base64.urlsafe_b64encode(bytes(tampered)).decode()

        with pytest.raises(EncryptionError):
            field_encryption.decrypt(tampered_b64)

    def test_detects_tampered_iv(self):
        """Test that tampered IV is detected (via HMAC verification)."""
        plaintext = "APIKey123"
        ciphertext = field_encryption.encrypt(plaintext)

        # Tamper with IV
        decoded = base64.urlsafe_b64decode(ciphertext.encode())
        tampered = bytearray(decoded)
        tampered[10] ^= 0x01  # Flip one bit in IV
        tampered_b64 = base64.urlsafe_b64encode(bytes(tampered)).decode()

        with pytest.raises(EncryptionError):
            field_encryption.decrypt(tampered_b64)


class TestEncryptionReversibility:
    """Test that encryption is properly reversible."""

    def test_encrypt_decrypt_cycle(self):
        """Test basic encrypt-decrypt cycle."""
        test_values = [
            "SimpleKey",
            "Key with spaces",
            "Key!@#$%^&*()",
            "VeryLongKey" * 100,
            "Unicode密码Key",
        ]

        for plaintext in test_values:
            ciphertext = field_encryption.encrypt(plaintext)
            decrypted = field_encryption.decrypt(ciphertext)
            assert decrypted == plaintext

    def test_multiple_encrypt_decrypt_cycles(self):
        """Test multiple encryption-decryption cycles."""
        plaintext = "APIKey123"

        # Encrypt and decrypt multiple times
        for _ in range(10):
            ciphertext = field_encryption.encrypt(plaintext)
            decrypted = field_encryption.decrypt(ciphertext)
            assert decrypted == plaintext

    def test_decrypt_old_ciphertext(self):
        """Test that old ciphertexts can still be decrypted."""
        plaintext = "APIKey123"
        ciphertext = field_encryption.encrypt(plaintext)

        # Simulate time passing
        time.sleep(0.1)

        # Should still decrypt correctly
        decrypted = field_encryption.decrypt(ciphertext)
        assert decrypted == plaintext


class TestConditionalEncryption:
    """Test conditional encryption helpers."""

    def test_encrypt_if_needed_with_plaintext(self):
        """Test encrypt_if_needed with plaintext."""
        plaintext = "APIKey123"
        result = field_encryption.encrypt_if_needed(plaintext)

        # Should be encrypted (starts with gAAAAA)
        assert result.startswith("gAAAAA")

        # Should decrypt correctly
        assert field_encryption.decrypt(result) == plaintext

    def test_encrypt_if_needed_with_already_encrypted(self):
        """Test encrypt_if_needed with already encrypted value."""
        plaintext = "APIKey123"
        encrypted = field_encryption.encrypt(plaintext)

        # Should return same value
        result = field_encryption.encrypt_if_needed(encrypted)
        assert result == encrypted

    def test_encrypt_if_needed_with_none(self):
        """Test encrypt_if_needed with None."""
        result = field_encryption.encrypt_if_needed(None)
        assert result is None

    def test_decrypt_if_needed_with_encrypted(self):
        """Test decrypt_if_needed with encrypted value."""
        plaintext = "APIKey123"
        ciphertext = field_encryption.encrypt(plaintext)

        result = field_encryption.decrypt_if_needed(ciphertext)
        assert result == plaintext

    def test_decrypt_if_needed_with_plaintext(self):
        """Test decrypt_if_needed with plaintext (legacy data)."""
        plaintext = "PlaintextKey"

        # Should return as-is
        result = field_encryption.decrypt_if_needed(plaintext)
        assert result == plaintext

    def test_decrypt_if_needed_with_none(self):
        """Test decrypt_if_needed with None."""
        result = field_encryption.decrypt_if_needed(None)
        assert result is None

    def test_decrypt_if_needed_with_invalid_encrypted(self):
        """Test decrypt_if_needed with invalid encrypted data."""
        # Looks encrypted but isn't valid
        invalid_encrypted = "gAAAAAInvalidData"

        # Should return original value on decryption failure
        result = field_encryption.decrypt_if_needed(invalid_encrypted)
        assert result == invalid_encrypted


class TestEncryptionPerformance:
    """Test encryption performance characteristics."""

    def test_encryption_is_fast_enough(self):
        """Test that encryption is fast enough for production use."""
        plaintext = "APIKey123"

        # Time 100 encryptions
        start = time.time()
        for _ in range(100):
            field_encryption.encrypt(plaintext)
        duration = time.time() - start

        # Should complete in under 1 second
        assert duration < 1.0

    def test_decryption_is_fast_enough(self):
        """Test that decryption is fast enough for production use."""
        plaintext = "APIKey123"
        ciphertext = field_encryption.encrypt(plaintext)

        # Time 100 decryptions
        start = time.time()
        for _ in range(100):
            field_encryption.decrypt(ciphertext)
        duration = time.time() - start

        # Should complete in under 1 second
        assert duration < 1.0


class TestEncryptionFormat:
    """Test encryption output format."""

    def test_ciphertext_is_base64_url_safe(self):
        """Test that ciphertext uses URL-safe base64 encoding."""
        plaintext = "APIKey123"
        ciphertext = field_encryption.encrypt(plaintext)

        # Should be valid URL-safe base64
        # Contains only: A-Z, a-z, 0-9, -, _
        pattern = r"^[A-Za-z0-9_-]+=*$"
        assert re.match(pattern, ciphertext)

    def test_ciphertext_starts_with_fernet_marker(self):
        """Test that ciphertext starts with Fernet version marker."""
        plaintext = "APIKey123"
        ciphertext = field_encryption.encrypt(plaintext)

        # Fernet tokens start with 'gAAAAA' (version 0x80 in base64)
        assert ciphertext.startswith("gAAAAA")

    def test_ciphertext_is_ascii_safe(self):
        """Test that ciphertext contains only ASCII characters."""
        plaintext = "APIKey123"
        ciphertext = field_encryption.encrypt(plaintext)

        assert ciphertext.isascii()

    def test_ciphertext_length_reasonable(self):
        """Test that ciphertext length is reasonable for database storage."""
        plaintext = "APIKey123"
        ciphertext = field_encryption.encrypt(plaintext)

        # Fernet adds overhead: version(1) + timestamp(8) + IV(16) + HMAC(32) = 57 bytes
        # Plus base64 encoding overhead and ciphertext
        # Should be less than 500 bytes for reasonable API keys
        assert len(ciphertext) < 500


class TestEncryptionDefenseInDepth:
    """Test defense-in-depth encryption security measures."""

    def test_authenticated_encryption_prevents_tampering(self):
        """Test that authenticated encryption prevents tampering attacks."""
        plaintext = "APIKey123"
        ciphertext = field_encryption.encrypt(plaintext)

        # Attacker tries to modify ciphertext
        attacks = [
            ciphertext[:-1],  # Truncate
            ciphertext + "X",  # Extend
            "X" + ciphertext[1:],  # Replace first char
            ciphertext[:-1] + "X",  # Replace last char
        ]

        for attack in attacks:
            with pytest.raises(EncryptionError):
                field_encryption.decrypt(attack)

    def test_encryption_prevents_plaintext_recovery_attacks(self):
        """Test that encryption prevents plaintext recovery without key."""
        plaintext = "APIKey123"
        ciphertext = field_encryption.encrypt(plaintext)

        # Ciphertext should not contain plaintext
        assert plaintext not in ciphertext

        # Decoded ciphertext should not contain plaintext
        decoded = base64.urlsafe_b64decode(ciphertext.encode())
        assert plaintext.encode() not in decoded

    def test_iv_randomness_prevents_pattern_analysis(self):
        """Test that IV randomness prevents pattern analysis attacks."""
        # Encrypt same plaintext multiple times
        plaintext = "APIKey123"
        ciphertexts = [field_encryption.encrypt(plaintext) for _ in range(10)]

        # All ciphertexts should be different (no patterns)
        assert len(set(ciphertexts)) == len(ciphertexts)

        # Extract and compare IVs
        ivs = []
        for ciphertext in ciphertexts:
            decoded = base64.urlsafe_b64decode(ciphertext.encode())
            iv = decoded[9:25]
            ivs.append(iv)

        # All IVs should be different
        assert len(set(ivs)) == len(ivs)
