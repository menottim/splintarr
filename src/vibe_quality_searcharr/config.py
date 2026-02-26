"""
Application configuration with Pydantic Settings and Docker secrets support.

This module provides secure configuration management following OWASP best practices:
- Docker secrets support (recommended for production)
- Environment variables fallback
- Secure defaults with validation
- Type-safe configuration
"""

import os
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings with Docker secrets support.

    Configuration hierarchy (highest priority first):
    1. Docker secrets (files in /run/secrets/)
    2. Environment variables
    3. .env file
    4. Default values
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application Settings
    environment: Literal["development", "production", "test"] = Field(
        default="production",
        description="Application environment",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Logging level",
    )
    app_name: str = Field(
        default="Vibe-Quality-Searcharr",
        description="Application name",
    )

    # Security Settings - JWT
    secret_key: str = Field(
        default="",
        description="JWT secret key (256-bit minimum). Use SECRET_KEY_FILE for Docker secrets.",
    )
    secret_key_file: str | None = Field(
        default=None,
        description="Path to secret key file (Docker secret)",
    )
    algorithm: str = Field(
        default="HS256",
        description="JWT signing algorithm",
    )
    access_token_expire_minutes: int = Field(
        default=15,
        description="Access token expiration time in minutes",
        ge=5,
        le=60,
    )
    refresh_token_expire_days: int = Field(
        default=30,
        description="Refresh token expiration time in days",
        ge=1,
        le=90,
    )

    # Security Settings - Password Hashing
    pepper: str = Field(
        default="",
        description="Global pepper for password hashing. Use PEPPER_FILE for Docker secrets.",
    )
    pepper_file: str | None = Field(
        default=None,
        description="Path to pepper file (Docker secret)",
    )
    argon2_memory_cost: int = Field(
        default=128 * 1024,  # 128 MiB
        description="Argon2 memory cost in KiB",
        ge=64 * 1024,  # Minimum 64 MiB
    )
    argon2_time_cost: int = Field(
        default=3,
        description="Argon2 time cost (iterations)",
        ge=2,
        le=10,
    )
    argon2_parallelism: int = Field(
        default=8,
        description="Argon2 parallelism factor",
        ge=1,
        le=16,
    )

    # Database Settings
    database_url: str = Field(
        default="sqlite:///./data/vibe-quality-searcharr.db",
        description="Database URL (without encryption key for SQLCipher)",
    )
    database_key: str = Field(
        default="",
        description="Database encryption key (32+ bytes). Use DATABASE_KEY_FILE for Docker secrets.",
    )
    database_key_file: str | None = Field(
        default=None,
        description="Path to database key file (Docker secret)",
    )
    database_cipher: str = Field(
        default="aes-256-cfb",
        description="SQLCipher cipher algorithm (whitelisted values only)",
    )
    database_kdf_iter: int = Field(
        default=256000,
        description="SQLCipher KDF iterations (must be between 64,000 and 10,000,000)",
        ge=64000,
        le=10000000,  # Add upper bound to prevent excessive CPU usage
    )

    # Server Settings
    host: str = Field(
        default="0.0.0.0",
        description="Server host",
    )
    port: int = Field(
        default=7337,
        description="Server port",
        ge=1,
        le=65535,
    )
    workers: int = Field(
        default=1,
        description="Number of worker processes",
        ge=1,
        le=8,
    )
    reload: bool = Field(
        default=False,
        description="Enable auto-reload (development only)",
    )

    # CORS Settings
    cors_origins: list[str] = Field(
        default=["http://localhost:7337"],
        description="Allowed CORS origins",
    )
    cors_allow_credentials: bool = Field(
        default=True,
        description="Allow credentials in CORS requests",
    )

    # Rate Limiting
    rate_limit_per_minute: int = Field(
        default=60,
        description="Global rate limit per minute per IP",
        ge=1,
        le=1000,
    )
    auth_rate_limit_per_minute: int = Field(
        default=5,
        description="Authentication endpoint rate limit per minute per IP",
        ge=1,
        le=20,
    )

    # Security Options
    allow_local_instances: bool = Field(
        default=False,
        description="Allow localhost/127.0.0.1 in instance URLs (development only)",
    )
    secure_cookies: bool = Field(
        default=True,
        description="Use secure flag on cookies (requires HTTPS)",
    )
    trusted_hosts: list[str] = Field(
        default=["localhost", "127.0.0.1"],
        description="Trusted host headers",
    )

    # Failed Login Protection
    max_failed_login_attempts: int = Field(
        default=5,  # Reduced from 10 to 5 per OWASP recommendations
        description="Maximum failed login attempts before account lockout",
        ge=3,
        le=20,
    )
    account_lockout_duration_minutes: int = Field(
        default=30,
        description="Account lockout duration in minutes after max failed attempts",
        ge=5,
        le=1440,  # Max 24 hours
    )

    # External API Settings
    api_request_timeout: int = Field(
        default=30,
        description="HTTP request timeout in seconds for external APIs",
        ge=5,
        le=120,
    )
    api_max_retries: int = Field(
        default=3,
        description="Maximum retry attempts for failed API requests",
        ge=0,
        le=5,
    )

    # Search Settings
    search_interval_hours: int = Field(
        default=24,
        description="Default search interval in hours",
        ge=1,
        le=168,  # Max 1 week
    )
    max_concurrent_searches: int = Field(
        default=5,
        description="Maximum concurrent search operations",
        ge=1,
        le=20,
    )

    def get_secret_key(self) -> str:
        """
        Retrieve secret key from file or environment variable.

        Hierarchy:
        1. Docker secret file (SECRET_KEY_FILE)
        2. Environment variable (SECRET_KEY)

        Returns:
            str: The secret key for JWT signing

        Raises:
            RuntimeError: If secret key is not configured or is too short
        """
        key = self._read_secret(self.secret_key_file, self.secret_key)
        if not key:
            raise RuntimeError(
                "SECRET_KEY not configured. Set SECRET_KEY or SECRET_KEY_FILE environment variable."
            )
        if len(key) < 32:
            raise RuntimeError("SECRET_KEY must be at least 32 characters (256 bits)")
        return key

    def get_pepper(self) -> str:
        """
        Retrieve pepper from file or environment variable.

        Hierarchy:
        1. Docker secret file (PEPPER_FILE)
        2. Environment variable (PEPPER)

        Returns:
            str: The pepper for password hashing

        Raises:
            RuntimeError: If pepper is not configured or is too short
        """
        pepper = self._read_secret(self.pepper_file, self.pepper)
        if not pepper:
            raise RuntimeError(
                "PEPPER not configured. Set PEPPER or PEPPER_FILE environment variable."
            )
        if len(pepper) < 32:
            raise RuntimeError("PEPPER must be at least 32 characters (256 bits)")
        return pepper

    def get_database_key(self) -> str:
        """
        Retrieve database encryption key from file or environment variable.

        Hierarchy:
        1. Docker secret file (DATABASE_KEY_FILE)
        2. Environment variable (DATABASE_KEY)

        Returns:
            str: The database encryption key for SQLCipher

        Raises:
            RuntimeError: If database key is not configured or is too short
        """
        key = self._read_secret(self.database_key_file, self.database_key)
        if not key:
            raise RuntimeError(
                "DATABASE_KEY not configured. Set DATABASE_KEY or DATABASE_KEY_FILE "
                "environment variable."
            )
        if len(key) < 32:
            raise RuntimeError("DATABASE_KEY must be at least 32 characters (256 bits)")
        return key

    def get_database_url(self) -> str:
        """
        Construct SQLCipher database URL.

        The encryption key and parameters are set via PRAGMA in the connection
        event listener (database.py), not in the URL. This is the correct approach
        for pysqlcipher3, which requires PRAGMA key to be set immediately after
        connecting.

        Returns:
            str: SQLCipher database URL (without embedded credentials)
        """
        from urllib.parse import urlparse

        # Extract base path from database_url
        # Handle both sqlite:/// and sqlite+pysqlcipher:/// schemes
        if "sqlite" in self.database_url:
            # Parse the URL to extract just the path (strip scheme and query params)
            parsed = urlparse(self.database_url)
            db_path = parsed.path
            if not db_path or db_path == "/":
                db_path = "/data/vibe-quality-searcharr.db"
        else:
            db_path = "/data/vibe-quality-searcharr.db"

        # Return URL without credentials - encryption is set via PRAGMA in event listener
        # The sqlite+pysqlcipher:// scheme tells SQLAlchemy to use pysqlcipher3 driver
        return f"sqlite+pysqlcipher://{db_path}"

    @staticmethod
    def _read_secret(file_path: str | None, env_value: str) -> str:
        """
        Read secret from file or return environment variable value.

        Args:
            file_path: Optional path to secret file (Docker secret)
            env_value: Value from environment variable

        Returns:
            str: The secret value
        """
        # Try Docker secret file first
        if file_path and os.path.exists(file_path):
            try:
                secret_file = Path(file_path)
                return secret_file.read_text().strip()
            except Exception as e:
                raise RuntimeError(f"Failed to read secret from {file_path}: {e}") from e

        # Fall back to environment variable
        return env_value

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        """Validate environment setting."""
        valid_environments = {"development", "production", "test"}
        if v not in valid_environments:
            raise ValueError(f"Invalid environment: {v}. Must be one of {valid_environments}")
        return v

    @field_validator("reload")
    @classmethod
    def validate_reload(cls, v: bool, info) -> bool:
        """Ensure reload is only enabled in development."""
        environment = info.data.get("environment", "production")
        if v and environment == "production":
            raise ValueError("Auto-reload cannot be enabled in production")
        return v

    @field_validator("secure_cookies")
    @classmethod
    def validate_secure_cookies(cls, v: bool, info) -> bool:
        """Warn if secure cookies are disabled in production."""
        environment = info.data.get("environment", "production")
        if not v and environment == "production":
            raise ValueError("Secure cookies must be enabled in production")
        return v

    @field_validator("database_cipher")
    @classmethod
    def validate_database_cipher(cls, v: str) -> str:
        """Validate cipher algorithm is in whitelist to prevent SQL injection."""
        allowed_ciphers = {
            "aes-256-cfb",
            "aes-256-cbc",
            "aes-128-cfb",
            "aes-128-cbc",
        }
        if v not in allowed_ciphers:
            raise ValueError(
                f"Invalid cipher: {v}. Allowed values: {', '.join(sorted(allowed_ciphers))}"
            )
        return v

    @field_validator("database_kdf_iter")
    @classmethod
    def validate_database_kdf_iter(cls, v: int) -> int:
        """Validate KDF iterations to prevent SQL injection and DoS."""
        if not isinstance(v, int):
            raise ValueError("kdf_iter must be an integer")
        if v < 64000:
            raise ValueError("kdf_iter must be at least 64,000 for security")
        if v > 10000000:
            raise ValueError("kdf_iter must not exceed 10,000,000 to prevent DoS")
        return v

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        """Validate JWT secret key meets minimum security requirements."""
        if not v:
            # Allow empty when SECRET_KEY_FILE is set (Docker secrets mode).
            # The get_secret_key() method will read from the file at runtime.
            if os.environ.get("SECRET_KEY_FILE"):
                return v
            raise ValueError(
                "JWT secret key is required. Set SECRET_KEY environment variable "
                "or use SECRET_KEY_FILE for Docker secrets."
            )
        if len(v) < 32:
            raise ValueError(
                f"JWT secret key must be at least 32 bytes (256 bits). "
                f"Current length: {len(v)} bytes. "
                f"Generate a secure key with: openssl rand -base64 32"
            )
        return v

    @field_validator("database_key")
    @classmethod
    def validate_database_key(cls, v: str) -> str:
        """Validate database encryption key meets minimum security requirements."""
        if not v:
            # Allow empty when DATABASE_KEY_FILE is set (Docker secrets mode).
            # The get_database_key() method will read from the file at runtime.
            if os.environ.get("DATABASE_KEY_FILE"):
                return v
            raise ValueError(
                "Database encryption key is required. Set DATABASE_KEY environment variable "
                "or use DATABASE_KEY_FILE for Docker secrets."
            )
        if len(v) < 32:
            raise ValueError(
                f"Database encryption key must be at least 32 bytes (256 bits). "
                f"Current length: {len(v)} bytes. "
                f"Generate a secure key with: openssl rand -base64 32"
            )
        return v

    @field_validator("pepper")
    @classmethod
    def validate_pepper(cls, v: str) -> str:
        """Validate password hashing pepper meets minimum security requirements."""
        if not v:
            # Allow empty when PEPPER_FILE is set (Docker secrets mode).
            # The get_pepper() method will read from the file at runtime.
            if os.environ.get("PEPPER_FILE"):
                return v
            raise ValueError(
                "Password hashing pepper is required. Set PEPPER environment variable "
                "or use PEPPER_FILE for Docker secrets."
            )
        if len(v) < 32:
            raise ValueError(
                f"Password hashing pepper must be at least 32 bytes (256 bits). "
                f"Current length: {len(v)} bytes. "
                f"Generate a secure key with: openssl rand -base64 32"
            )
        return v


# Global settings instance
settings = Settings()
