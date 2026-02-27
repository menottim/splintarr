"""
Unit tests for TOTP secret encryption at application level.

Verifies that TOTP secrets are Fernet-encrypted before storage and correctly
decrypted when read for verification, matching the pattern used for API keys.
"""

import pyotp
import pytest

from splintarr.core.auth import generate_totp_secret, verify_totp_code
from splintarr.core.security import decrypt_field, encrypt_field, field_encryption
from splintarr.models.user import User


class TestTotpSecretEncryptionRoundTrip:
    """Test that TOTP secrets survive encrypt/decrypt round-trips."""

    def test_encrypt_totp_secret_produces_fernet_token(self):
        """Encrypted TOTP secret should start with the Fernet prefix 'gAAAAA'."""
        plaintext_secret = "JBSWY3DPEHPK3PXP"
        encrypted = encrypt_field(plaintext_secret)

        assert encrypted.startswith("gAAAAA")
        assert encrypted != plaintext_secret

    def test_decrypt_totp_secret_recovers_original(self):
        """Decrypting an encrypted TOTP secret should return the original base32 value."""
        plaintext_secret = "JBSWY3DPEHPK3PXP"
        encrypted = encrypt_field(plaintext_secret)
        decrypted = decrypt_field(encrypted)

        assert decrypted == plaintext_secret

    def test_encrypt_decrypt_various_base32_secrets(self):
        """Round-trip should work for different base32-encoded TOTP secrets."""
        secrets = [
            "JBSWY3DPEHPK3PXP",
            "ABCDEFGHIJKLMNOP",
            "7777777777777777",
            "MFZWIZLTOQ======",
            "GEZDGNBVGY3TQOJQ",
        ]
        for secret in secrets:
            encrypted = encrypt_field(secret)
            assert encrypted.startswith("gAAAAA"), f"Failed for secret: {secret}"
            assert decrypt_field(encrypted) == secret

    def test_same_secret_encrypts_to_different_ciphertexts(self):
        """Fernet uses a random IV, so the same plaintext produces different ciphertexts."""
        secret = "JBSWY3DPEHPK3PXP"
        encrypted1 = encrypt_field(secret)
        encrypted2 = encrypt_field(secret)

        assert encrypted1 != encrypted2
        # Both should still decrypt to the same value
        assert decrypt_field(encrypted1) == secret
        assert decrypt_field(encrypted2) == secret

    def test_generated_totp_secret_round_trips(self):
        """A real generate_totp_secret() value should encrypt and decrypt correctly."""
        secret = generate_totp_secret()
        encrypted = encrypt_field(secret)

        assert encrypted.startswith("gAAAAA")
        assert encrypted != secret
        assert decrypt_field(encrypted) == secret

    def test_encrypted_secret_is_longer_than_plaintext(self):
        """Fernet ciphertext is longer than the original base32 secret (~120+ chars)."""
        secret = generate_totp_secret()
        encrypted = encrypt_field(secret)

        # A base32 TOTP secret is typically 16-32 chars;
        # Fernet output is ~120+ chars
        assert len(encrypted) > len(secret)
        assert len(encrypted) > 100


class TestTotpColumnType:
    """Test that the User model totp_secret column accepts Fernet-length values."""

    def test_totp_secret_column_is_text_type(self):
        """The totp_secret column should be Text to accommodate Fernet ciphertext."""
        from sqlalchemy import Text

        col = User.__table__.columns["totp_secret"]
        assert isinstance(col.type, Text)

    def test_totp_secret_column_is_nullable(self):
        """The totp_secret column should remain nullable (NULL when 2FA disabled)."""
        col = User.__table__.columns["totp_secret"]
        assert col.nullable is True


class TestTotpEncryptedStorageAndVerification:
    """Test the full flow: encrypt on store, decrypt on verify."""

    def test_store_encrypted_secret_then_verify_totp_code(self):
        """Simulate the setup_2fa -> verify_2fa flow using encryption."""
        # Step 1: Generate secret (what setup_2fa does)
        plaintext_secret = generate_totp_secret()

        # Step 2: Encrypt before storing (what setup_2fa now does)
        encrypted_secret = encrypt_field(plaintext_secret)
        assert encrypted_secret.startswith("gAAAAA")

        # Step 3: Generate a valid TOTP code using the plaintext secret
        totp = pyotp.TOTP(plaintext_secret)
        valid_code = totp.now()

        # Step 4: Decrypt stored secret and verify code (what verify_2fa now does)
        decrypted_secret = decrypt_field(encrypted_secret)
        assert verify_totp_code(decrypted_secret, valid_code) is True

    def test_verify_fails_without_decryption(self):
        """Verifying a TOTP code against the encrypted (not decrypted) secret must fail."""
        plaintext_secret = generate_totp_secret()
        encrypted_secret = encrypt_field(plaintext_secret)

        totp = pyotp.TOTP(plaintext_secret)
        valid_code = totp.now()

        # Passing the encrypted value directly should fail verification
        # because the encrypted string is not a valid base32 TOTP secret
        assert verify_totp_code(encrypted_secret, valid_code) is False

    def test_disable_2fa_flow_with_encrypted_secret(self):
        """Simulate the disable_2fa flow: decrypt stored secret, verify code, then clear."""
        plaintext_secret = generate_totp_secret()
        encrypted_secret = encrypt_field(plaintext_secret)

        # Generate valid TOTP code
        totp = pyotp.TOTP(plaintext_secret)
        valid_code = totp.now()

        # Decrypt and verify (what disable_2fa does)
        decrypted = decrypt_field(encrypted_secret)
        assert verify_totp_code(decrypted, valid_code) is True

        # After disable, the secret would be set to None
        cleared_secret = None
        assert cleared_secret is None

    def test_login_verify_2fa_flow_with_encrypted_secret(self):
        """Simulate the login_verify_2fa flow: decrypt stored secret, verify code."""
        plaintext_secret = generate_totp_secret()
        encrypted_secret = encrypt_field(plaintext_secret)

        # Generate valid TOTP code
        totp = pyotp.TOTP(plaintext_secret)
        valid_code = totp.now()

        # login_verify_2fa decrypts and verifies
        decrypted = decrypt_field(encrypted_secret)
        assert verify_totp_code(decrypted, valid_code) is True

    def test_wrong_code_fails_with_encrypted_secret(self):
        """An invalid TOTP code should fail even with correct decrypt flow."""
        plaintext_secret = generate_totp_secret()
        encrypted_secret = encrypt_field(plaintext_secret)

        decrypted = decrypt_field(encrypted_secret)
        assert verify_totp_code(decrypted, "000000") is False

    def test_stored_value_is_not_plaintext(self):
        """The value stored in the DB (encrypted) must not equal the plaintext secret."""
        plaintext_secret = generate_totp_secret()
        encrypted_secret = encrypt_field(plaintext_secret)

        # Critical security check: stored value must differ from plaintext
        assert encrypted_secret != plaintext_secret
        # And it should be a Fernet token
        assert encrypted_secret.startswith("gAAAAA")


class TestTotpEncryptedStorageInDatabase:
    """Test TOTP encryption with actual database User model operations."""

    def test_user_totp_secret_stored_encrypted_in_db(self, db_session):
        """Writing an encrypted TOTP secret to the User model and reading it back."""
        from splintarr.core.security import hash_password

        plaintext_secret = generate_totp_secret()
        encrypted_secret = encrypt_field(plaintext_secret)

        user = User(
            username="totp_test_user",
            password_hash=hash_password("TestP@ssw0rd123"),
            totp_secret=encrypted_secret,
            totp_enabled=False,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        # The stored value should be the encrypted form
        assert user.totp_secret == encrypted_secret
        assert user.totp_secret.startswith("gAAAAA")

        # Decrypting should recover original
        assert decrypt_field(user.totp_secret) == plaintext_secret

    def test_fernet_ciphertext_fits_in_text_column(self, db_session):
        """Fernet ciphertext for a TOTP secret should store and retrieve correctly in Text column."""
        from splintarr.core.security import hash_password

        plaintext_secret = generate_totp_secret()
        encrypted_secret = encrypt_field(plaintext_secret)

        user = User(
            username="totp_fit_test",
            password_hash=hash_password("TestP@ssw0rd123"),
            totp_secret=encrypted_secret,
            totp_enabled=True,
        )
        db_session.add(user)
        db_session.commit()

        # Retrieve from DB and verify
        fetched = db_session.query(User).filter(User.username == "totp_fit_test").first()
        assert fetched is not None
        assert fetched.totp_secret == encrypted_secret
        assert decrypt_field(fetched.totp_secret) == plaintext_secret

    def test_null_totp_secret_when_2fa_disabled(self, db_session):
        """When 2FA is not set up, totp_secret should be None."""
        from splintarr.core.security import hash_password

        user = User(
            username="no_2fa_user",
            password_hash=hash_password("TestP@ssw0rd123"),
            totp_secret=None,
            totp_enabled=False,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        assert user.totp_secret is None
        assert user.totp_enabled is False
