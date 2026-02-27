"""
Pydantic schemas for Instance management.

This module defines request and response models for Instance endpoints:
- Creating and updating Sonarr/Radarr instances
- Connection testing and health monitoring
- Instance configuration management
- SSRF protection for instance URLs
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator

from splintarr.config import settings
from splintarr.core.ssrf_protection import SSRFError, validate_instance_url

# Instance types
InstanceType = Literal["sonarr", "radarr"]


class InstanceCreate(BaseModel):
    """
    Schema for creating a new Sonarr/Radarr instance.

    Used for adding new media management instances.
    """

    name: str = Field(
        ...,
        min_length=3,
        max_length=50,
        description="User-friendly name for the instance (3-50 characters)",
    )
    instance_type: InstanceType = Field(
        ...,
        description="Type of instance (sonarr or radarr)",
    )
    url: HttpUrl = Field(
        ...,
        description="Base URL of the instance (e.g., https://sonarr.example.com)",
    )
    api_key: str = Field(
        ...,
        min_length=32,
        max_length=100,
        description="API key for instance authentication (will be encrypted)",
    )
    verify_ssl: bool = Field(
        default=True,
        description="Whether to verify SSL certificates (recommended: True)",
    )

    @field_validator("url")
    @classmethod
    def validate_url_ssrf(cls, v: HttpUrl) -> HttpUrl:
        """Validate URL against SSRF attacks."""
        url_str = str(v)

        try:
            # Check for SSRF (respects allow_local_instances setting)
            validate_instance_url(url_str, allow_local=settings.allow_local_instances)
        except SSRFError as e:
            raise ValueError(f"URL blocked for security: {e}") from e
        except Exception as e:
            raise ValueError(f"Invalid URL: {e}") from e

        return v

    timeout_seconds: int = Field(
        default=30,
        ge=5,
        le=120,
        description="HTTP request timeout in seconds (5-120)",
    )
    rate_limit_per_minute: int = Field(
        default=60,
        ge=10,
        le=300,
        description="Maximum requests per minute to this instance (10-300)",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """
        Validate instance name format.

        Instance name must:
        - Be 3-50 characters long
        - Not be only whitespace

        Args:
            v: Instance name to validate

        Returns:
            str: Validated name

        Raises:
            ValueError: If name format is invalid
        """
        stripped = v.strip()
        if not stripped:
            raise ValueError("Instance name cannot be empty or only whitespace")

        if len(stripped) < 3:
            raise ValueError("Instance name must be at least 3 characters long")

        return stripped

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        """
        Validate API key format.

        API key must:
        - Be at least 20 characters long
        - Not be only whitespace
        - Not contain obviously invalid characters

        Args:
            v: API key to validate

        Returns:
            str: Validated API key

        Raises:
            ValueError: If API key format is invalid
        """
        stripped = v.strip()
        if not stripped:
            raise ValueError("API key cannot be empty or only whitespace")

        if len(stripped) < 20:
            raise ValueError(
                "API key must be at least 20 characters long. "
                "Check your Sonarr/Radarr settings for the correct API key."
            )

        # Check for common mistakes
        if " " in stripped:
            raise ValueError("API key should not contain spaces")

        return stripped

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "Primary Sonarr",
                    "instance_type": "sonarr",
                    "url": "https://sonarr.example.com",
                    "api_key": "abc123def456ghi789jkl012mno345pqr678",
                    "verify_ssl": True,
                    "timeout_seconds": 30,
                    "rate_limit_per_minute": 60,
                }
            ]
        }
    }


class InstanceUpdate(BaseModel):
    """
    Schema for updating an existing instance.

    All fields are optional. Only provided fields will be updated.
    """

    name: str | None = Field(
        default=None,
        min_length=3,
        max_length=50,
        description="User-friendly name for the instance (3-50 characters)",
    )
    url: HttpUrl | None = Field(
        default=None,
        description="Base URL of the instance",
    )
    api_key: str | None = Field(
        default=None,
        min_length=32,
        max_length=100,
        description="API key for instance authentication (will be encrypted)",
    )
    verify_ssl: bool | None = Field(
        default=None,
        description="Whether to verify SSL certificates",
    )
    timeout_seconds: int | None = Field(
        default=None,
        ge=5,
        le=120,
        description="HTTP request timeout in seconds (5-120)",
    )
    rate_limit_per_minute: int | None = Field(
        default=None,
        ge=10,
        le=300,
        description="Maximum requests per minute to this instance (10-300)",
    )

    @field_validator("url")
    @classmethod
    def validate_url_ssrf(cls, v: HttpUrl | None) -> HttpUrl | None:
        """Validate URL against SSRF attacks if provided."""
        if v is None:
            return v

        url_str = str(v)

        try:
            # Check for SSRF (respects allow_local_instances setting)
            validate_instance_url(url_str, allow_local=settings.allow_local_instances)
        except SSRFError as e:
            raise ValueError(f"URL blocked for security: {e}") from e
        except Exception as e:
            raise ValueError(f"Invalid URL: {e}") from e

        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        """Validate instance name format if provided."""
        if v is None:
            return v

        stripped = v.strip()
        if not stripped:
            raise ValueError("Instance name cannot be empty or only whitespace")

        if len(stripped) < 3:
            raise ValueError("Instance name must be at least 3 characters long")

        return stripped

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str | None) -> str | None:
        """Validate API key format if provided."""
        if v is None:
            return v

        stripped = v.strip()
        if not stripped:
            raise ValueError("API key cannot be empty or only whitespace")

        if len(stripped) < 20:
            raise ValueError(
                "API key must be at least 20 characters long. "
                "Check your Sonarr/Radarr settings for the correct API key."
            )

        if " " in stripped:
            raise ValueError("API key should not contain spaces")

        return stripped

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "Updated Sonarr Name",
                    "timeout_seconds": 45,
                }
            ]
        }
    }


class InstanceResponse(BaseModel):
    """
    Schema for instance information response.

    Returned when fetching instance details.
    Note: API key is NEVER exposed in responses.
    """

    id: int = Field(..., description="Instance ID")
    name: str = Field(..., description="User-friendly name")
    instance_type: InstanceType = Field(..., description="Instance type (sonarr or radarr)")
    url: str = Field(..., description="Base URL of the instance")
    verify_ssl: bool = Field(..., description="Whether SSL verification is enabled")
    timeout_seconds: int = Field(..., description="HTTP request timeout in seconds")
    rate_limit_per_minute: int = Field(..., description="Maximum requests per minute")
    is_healthy: bool = Field(..., description="Whether last connection test was successful")
    last_connection_test: datetime | None = Field(
        None, description="Last connection test timestamp (ISO 8601)"
    )
    last_connection_success: bool | None = Field(
        None, description="Result of last connection test (NULL if never tested)"
    )
    last_error: str | None = Field(None, description="Error message from last failed connection")
    created_at: datetime = Field(..., description="Instance creation timestamp (ISO 8601)")
    updated_at: datetime = Field(..., description="Last update timestamp (ISO 8601)")
    security_warning: str | None = Field(
        None, description="Security warning if SSL verification is disabled"
    )

    @field_validator("security_warning", mode="before")
    @classmethod
    def add_security_warning(cls, v: Any, info) -> str | None:
        """Add security warning if SSL verification is disabled."""
        # Get verify_ssl from the values being validated
        if hasattr(info, "data") and not info.data.get("verify_ssl", True):
            return (
                "WARNING: SSL certificate verification is disabled. "
                "This connection is vulnerable to man-in-the-middle attacks. "
                "Enable SSL verification in production environments."
            )
        return None

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "name": "Primary Sonarr",
                    "instance_type": "sonarr",
                    "url": "https://sonarr.example.com",
                    "verify_ssl": True,
                    "timeout_seconds": 30,
                    "rate_limit_per_minute": 60,
                    "is_healthy": True,
                    "last_connection_test": "2024-01-15T14:22:15Z",
                    "last_connection_success": True,
                    "last_error": None,
                    "created_at": "2024-01-15T10:30:00Z",
                    "updated_at": "2024-01-15T14:22:15Z",
                    "security_warning": None,
                }
            ]
        },
    }


class InstanceTestResult(BaseModel):
    """
    Schema for instance connection test result.

    Returned when testing connection to a Sonarr/Radarr instance.
    """

    success: bool = Field(..., description="Whether the connection test succeeded")
    message: str = Field(..., description="Human-readable test result message")
    version: str | None = Field(None, description="Sonarr/Radarr version if connection successful")
    response_time_ms: int | None = Field(None, description="Response time in milliseconds")
    items_count: int | None = Field(
        None, description="Number of series (Sonarr) or movies (Radarr) in the library"
    )
    error_details: str | None = Field(None, description="Detailed error information if test failed")
    instance_info: str | None = Field(
        None, description="Instance details from system status (e.g., app name, OS)"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "message": "Successfully connected to Sonarr instance",
                    "version": "3.0.10.1567",
                    "response_time_ms": 245,
                    "items_count": 42,
                    "error_details": None,
                    "instance_info": "Sonarr on linux (docker)",
                },
                {
                    "success": False,
                    "message": "Failed to connect to instance",
                    "version": None,
                    "response_time_ms": None,
                    "items_count": None,
                    "error_details": "Connection timeout after 30 seconds",
                    "instance_info": None,
                },
            ]
        }
    }
