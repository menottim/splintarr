"""
Application configuration with Pydantic Settings and Docker secrets support.

This module provides secure configuration management following OWASP best practices:
- Docker secrets support (recommended for production)
- Environment variables fallback
- Secure defaults with validation
- Type-safe configuration
"""

import os
import sys
from pathlib import Path
from typing import Literal

import structlog
from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = structlog.get_logger()


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
        default="Splintarr",
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
        default="sqlite:///./data/splintarr.db",
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

    # Library Sync Settings
    library_sync_interval_hours: int = Field(
        default=6,
        description="Hours between automatic library syncs from Sonarr/Radarr",
        ge=1,
        le=168,
    )

    # Search Feedback Loop
    feedback_check_delay_minutes: int = Field(
        default=15,
        description="Minutes to wait before checking search command results for grabs",
        ge=5,
        le=60,
    )

    # Health Monitoring Settings
    health_check_interval_minutes: int = Field(
        default=5,
        description="Minutes between automatic instance health checks",
        ge=1,
        le=60,
    )
    health_check_recovery_threshold: int = Field(
        default=2,
        description="Consecutive healthy checks required before resuming queues",
        ge=1,
        le=10,
    )

    def _get_secret(self, name: str, file_path: str | None, env_value: str) -> str:
        """
        Retrieve a secret from file or environment variable.

        Hierarchy:
        1. Docker secret file ({name}_FILE)
        2. Environment variable ({name})

        Args:
            name: Secret name for error messages (e.g., "SECRET_KEY")
            file_path: Optional path to secret file (Docker secret)
            env_value: Value from environment variable

        Returns:
            str: The secret value

        Raises:
            RuntimeError: If secret is not configured or is too short
        """
        value = self._read_secret(file_path, env_value)
        if not value:
            raise RuntimeError(
                f"{name} not configured. Set {name} or {name}_FILE environment variable."
            )
        if len(value) < 32:
            raise RuntimeError(f"{name} must be at least 32 characters (256 bits)")
        return value

    def get_secret_key(self) -> str:
        """Retrieve JWT secret key from file or environment variable."""
        return self._get_secret("SECRET_KEY", self.secret_key_file, self.secret_key)

    def get_pepper(self) -> str:
        """Retrieve password hashing pepper from file or environment variable."""
        return self._get_secret("PEPPER", self.pepper_file, self.pepper)

    def get_database_key(self) -> str:
        """Retrieve database encryption key from file or environment variable."""
        return self._get_secret("DATABASE_KEY", self.database_key_file, self.database_key)

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
                db_path = "/data/splintarr.db"
        else:
            db_path = "/data/splintarr.db"

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
        if file_path:
            secret_path = Path(file_path)
            if secret_path.exists():
                try:
                    return secret_path.read_text().strip()
                except Exception as e:
                    raise RuntimeError(f"Failed to read secret from {file_path}: {e}") from e

        # Fall back to environment variable
        return env_value

    @field_validator("algorithm")
    @classmethod
    def validate_algorithm(cls, v: str) -> str:
        """Constrain JWT algorithm to HS256 to prevent algorithm confusion attacks."""
        if v != "HS256":
            raise ValueError(f"Invalid JWT algorithm: {v}. Only 'HS256' is allowed.")
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

    @staticmethod
    def _validate_secret_field(v: str, field_name: str, display_name: str) -> str:
        """
        Validate a secret field meets minimum security requirements.

        Allows empty values when the corresponding _FILE env var is set
        (Docker secrets mode), since the get_* methods read from file at runtime.
        """
        if not v:
            if os.environ.get(f"{field_name}_FILE"):
                return v
            raise ValueError(
                f"{display_name} is required. Set {field_name} environment variable "
                f"or use {field_name}_FILE for Docker secrets."
            )
        if len(v) < 32:
            raise ValueError(
                f"{display_name} must be at least 32 bytes (256 bits). "
                "Generate a secure key with: openssl rand -base64 32"
            )
        return v

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        """Validate JWT secret key meets minimum security requirements."""
        return cls._validate_secret_field(v, "SECRET_KEY", "JWT secret key")

    @field_validator("database_key")
    @classmethod
    def validate_database_key(cls, v: str) -> str:
        """Validate database encryption key meets minimum security requirements."""
        return cls._validate_secret_field(v, "DATABASE_KEY", "Database encryption key")

    @field_validator("pepper")
    @classmethod
    def validate_pepper(cls, v: str) -> str:
        """Validate password hashing pepper meets minimum security requirements."""
        return cls._validate_secret_field(v, "PEPPER", "Password hashing pepper")


# Global settings instance
try:
    settings = Settings()
except ValidationError as e:
    # Log a generic error without secret values that Pydantic may include in the message.
    # ValidationError.__str__() can contain the raw input values for secret fields.
    error_fields = [err.get("loc", ("unknown",))[0] for err in e.errors()]
    logger.critical(
        "settings_validation_failed",
        fields=error_fields,
        hint="Check environment variables or Docker secrets. "
        "Run 'scripts/generate-secrets.sh' to generate required secrets.",
    )
    sys.exit(1)
