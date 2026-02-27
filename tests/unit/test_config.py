"""Tests for configuration management."""

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from splintarr.config import Settings


def test_settings_defaults():
    """Test default settings values."""
    settings = Settings(
        secret_key="test_secret",
        pepper="test_pepper",
        database_key="test_db_key"
    )

    assert settings.app_name == "Splintarr"
    assert settings.environment == "development"
    assert settings.port == 7337
    assert settings.session_expire_hours == 24
    assert settings.access_token_expire_minutes == 15
    assert settings.argon2_memory_cost == 131072  # 128 MiB


def test_settings_environment_validation():
    """Test environment validation."""
    with pytest.raises(ValidationError):
        Settings(
            environment="invalid",
            secret_key="test",
            pepper="test",
            database_key="test"
        )


def test_argon2_memory_cost_power_of_two():
    """Test that Argon2 memory cost must be power of 2."""
    # Valid: 131072 = 2^17
    settings = Settings(
        argon2_memory_cost=131072,
        secret_key="test",
        pepper="test",
        database_key="test"
    )
    assert settings.argon2_memory_cost == 131072

    # Invalid: not power of 2
    with pytest.raises(ValidationError):
        Settings(
            argon2_memory_cost=100000,
            secret_key="test",
            pepper="test",
            database_key="test"
        )


def test_get_secret_from_environment():
    """Test reading secret from environment variable."""
    settings = Settings(
        secret_key="env_secret",
        pepper="env_pepper",
        database_key="env_db_key"
    )

    assert settings.get_secret_key() == "env_secret"
    assert settings.get_pepper() == "env_pepper"
    assert settings.get_database_key() == "env_db_key"


def test_get_secret_from_file(temp_secrets_dir):
    """Test reading secret from Docker secret file."""
    # Create secret files
    secret_file = temp_secrets_dir / "secret_key.txt"
    secret_file.write_text("file_secret_key")

    pepper_file = temp_secrets_dir / "pepper.txt"
    pepper_file.write_text("file_pepper")

    db_key_file = temp_secrets_dir / "db_key.txt"
    db_key_file.write_text("file_db_key")

    settings = Settings(
        secret_key_file=str(secret_file),
        pepper_file=str(pepper_file),
        database_key_file=str(db_key_file)
    )

    assert settings.get_secret_key() == "file_secret_key"
    assert settings.get_pepper() == "file_pepper"
    assert settings.get_database_key() == "file_db_key"


def test_get_secret_file_not_found():
    """Test error when secret file doesn't exist."""
    settings = Settings(
        secret_key_file="/nonexistent/secret.txt",
        pepper="test_pepper",
        database_key="test_db_key"
    )

    with pytest.raises(ValueError, match="specified but does not exist"):
        settings.get_secret_key()


def test_get_secret_file_empty(temp_secrets_dir):
    """Test error when secret file is empty."""
    empty_file = temp_secrets_dir / "empty.txt"
    empty_file.write_text("")

    settings = Settings(
        secret_key_file=str(empty_file),
        pepper="test_pepper",
        database_key="test_db_key"
    )

    with pytest.raises(ValueError, match="exists but is empty"):
        settings.get_secret_key()


def test_get_secret_not_configured():
    """Test error when secret is not configured."""
    settings = Settings()

    with pytest.raises(ValueError, match="not configured"):
        settings.get_secret_key()


def test_allowed_origins_list():
    """Test parsing allowed origins into list."""
    settings = Settings(
        allowed_origins="http://localhost:8000,https://example.com",
        secret_key="test",
        pepper="test",
        database_key="test"
    )

    origins = settings.get_allowed_origins_list()
    assert len(origins) == 2
    assert "http://localhost:8000" in origins
    assert "https://example.com" in origins


def test_is_production():
    """Test production environment detection."""
    dev_settings = Settings(
        environment="development",
        secret_key="test",
        pepper="test",
        database_key="test"
    )
    assert dev_settings.is_development
    assert not dev_settings.is_production

    prod_settings = Settings(
        environment="production",
        secret_key="test",
        pepper="test",
        database_key="test"
    )
    assert prod_settings.is_production
    assert not prod_settings.is_development
