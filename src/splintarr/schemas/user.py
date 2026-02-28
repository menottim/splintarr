"""
Pydantic schemas for user authentication and authorization.

This module defines request and response models for authentication endpoints:
- User registration and login
- JWT token responses
- Two-factor authentication setup and verification
"""

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Common password blocklist (case-insensitive comparison).
# Based on NIST SP 800-63B recommendation to check breached/common passwords.
# Shared between UserRegister schema and setup wizard validation.
common_passwords = {
    "password",
    "password123",
    "password1",
    "password12",
    "123456",
    "12345678",
    "123456789",
    "1234567890",
    "qwerty",
    "qwerty123",
    "qwerty12345",
    "abc123",
    "abcdef",
    "abcdefg",
    "admin",
    "admin123",
    "administrator",
    "letmein",
    "welcome",
    "welcome123",
    "welcome1",
    "monkey",
    "dragon",
    "master",
    "shadow",
    "passw0rd",
    "p@ssw0rd",
    "p@ssword",
    "p@ssw0rd!",
    "iloveyou",
    "sunshine",
    "princess",
    "starwars",
    "trustno1",
    "baseball",
    "football",
    "soccer",
    "michael",
    "jordan",
    "jennifer",
    "jessica",
    "charlie",
    "thomas",
    "robert",
    "daniel",
    "access",
    "master123",
    "hello123",
    "test123",
    "changeme",
    "changeme123",
    "default",
    "temp123",
    "batman",
    "superman",
    "spider-man",
    "matrix",
    "killer",
    "hunter",
    "ranger",
    "buster",
    "mustang",
    "harley",
    "tigger",
    "pepper",
    "george",
    "andrew",
    "joshua",
    "freedom",
    "computer",
    "internet",
    "server",
    "network",
    "letmein123",
    "login",
    "admin1234",
    "root",
    "toor",
    "pass",
    "test",
    "guest",
    "secret",
    "secret123",
    "mysecret",
    "security",
    "password!",
    "p@ssword!",
    "p@ssword1",
    "passw0rd!",
    "qwerty!",
    "qwerty1!",
    "asdfgh",
    "zxcvbn",
    "nothing",
    "summer",
    "winter",
    "spring",
    "aaaaaa",
    "111111",
    "000000",
    "121212",
    "654321",
    "696969",
    "112233",
    "123123",
    "abc123!",
    "test1234",
    "password2",
    "password3",
    "letmein!",
    "welcome!",
    "hello",
    "lovely",
    "whatever",
    "fantasy",
    "pokemon",
    "please",
    "diamond",
    "angel",
    "friends",
    "flower",
    "hotdog",
    "hammer",
    "purple",
    "simple",
}


class UserRegister(BaseModel):
    """
    Schema for user registration.

    Used for first-run registration (only when no users exist).
    """

    username: str = Field(
        ...,
        min_length=3,
        max_length=32,
        description="Username (3-32 alphanumeric characters and underscore)",
    )
    password: str = Field(
        ...,
        min_length=12,
        max_length=128,
        description="Password (minimum 12 characters)",
    )

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        """
        Validate username format.

        Username must:
        - Be 3-32 characters long
        - Contain only alphanumeric characters and underscore
        - Start with a letter

        Args:
            v: Username to validate

        Returns:
            str: Validated username

        Raises:
            ValueError: If username format is invalid
        """
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9_]*$", v):
            raise ValueError(
                "Username must start with a letter and contain only "
                "alphanumeric characters and underscore"
            )
        return v

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """
        Validate password complexity requirements.

        Password must:
        - Be at least 12 characters long (max 128 to prevent Argon2 DoS)
        - Contain at least one lowercase letter
        - Contain at least one uppercase letter
        - Contain at least one digit
        - Contain at least one special character
        - Not be in common password list

        Args:
            v: Password to validate

        Returns:
            str: Validated password (case-preserved)

        Raises:
            ValueError: If password doesn't meet complexity requirements
        """
        if len(v) < 12:
            raise ValueError("Password must be at least 12 characters long")

        if len(v) > 128:
            raise ValueError("Password must not exceed 128 characters")

        # Check for required character types
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")

        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")

        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least one digit")

        if not re.search(r'[!@#$%^&*(),.?":{}|<>_\-+=\[\]\\;/`~]', v):
            raise ValueError("Password must contain at least one special character")

        # Check against common passwords (case-insensitive comparison)
        if v.lower() in common_passwords:
            raise ValueError("Password is too common. Please choose a more unique password.")

        # Return password with original case preserved (never normalize)
        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "username": "admin",
                    "password": "SecureP@ssw0rd123!",
                }
            ]
        }
    }


class UserLogin(BaseModel):
    """
    Schema for user login.

    Used for authentication with username and password.
    """

    username: str = Field(
        ...,
        min_length=3,
        max_length=32,
        description="Username",
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Password",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "username": "admin",
                    "password": "SecureP@ssw0rd123!",
                }
            ]
        }
    }


class TokenResponse(BaseModel):
    """
    Schema for token response.

    Returned after successful login or token refresh.
    Note: In production, tokens are sent as HTTP-only cookies,
    but this schema can also be used for API responses if needed.
    """

    access_token: str = Field(
        ...,
        description="JWT access token (15-minute expiry)",
    )
    refresh_token: str = Field(
        ...,
        description="JWT refresh token (30-day expiry)",
    )
    token_type: Literal["bearer"] = Field(
        default="bearer",
        description="Token type (always 'bearer')",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                    "token_type": "bearer",
                }
            ]
        }
    }


class UserResponse(BaseModel):
    """
    Schema for user information response.

    Returned after successful registration or when fetching user details.
    """

    id: int = Field(..., description="User ID")
    username: str = Field(..., description="Username")
    is_active: bool = Field(..., description="Whether the account is active")
    is_superuser: bool = Field(..., description="Whether the user has superuser privileges")
    totp_enabled: bool = Field(default=False, description="Whether 2FA is enabled")
    created_at: str = Field(..., description="Account creation timestamp (ISO 8601)")
    last_login: str | None = Field(None, description="Last login timestamp (ISO 8601)")

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "username": "admin",
                    "is_active": True,
                    "is_superuser": True,
                    "totp_enabled": False,
                    "created_at": "2024-01-15T10:30:00Z",
                    "last_login": "2024-01-15T14:22:15Z",
                }
            ]
        },
    }


class TwoFactorSetup(BaseModel):
    """
    Schema for two-factor authentication setup response.

    Contains the TOTP secret, QR code URI, and pre-rendered QR code image.
    """

    secret: str = Field(
        ...,
        description="Base32-encoded TOTP secret (store this securely)",
    )
    qr_code_uri: str = Field(
        ...,
        description="otpauth:// URI for QR code generation",
    )
    qr_code_data_uri: str = Field(
        ...,
        description="QR code as data:image/png;base64,... for embedding in HTML",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "secret": "JBSWY3DPEHPK3PXP",
                    "qr_code_uri": "otpauth://totp/Splintarr:admin?secret=JBSWY3DPEHPK3PXP&issuer=Splintarr",
                    "qr_code_data_uri": "data:image/png;base64,...",
                }
            ]
        }
    }


class TwoFactorVerify(BaseModel):
    """
    Schema for two-factor authentication verification.

    Used to verify a TOTP code during 2FA setup or login.
    """

    code: str = Field(
        ...,
        min_length=6,
        max_length=6,
        pattern=r"^\d{6}$",
        description="6-digit TOTP code from authenticator app",
    )

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        """
        Validate TOTP code format.

        Args:
            v: TOTP code to validate

        Returns:
            str: Validated TOTP code

        Raises:
            ValueError: If code is not 6 digits
        """
        if not v.isdigit():
            raise ValueError("TOTP code must contain only digits")

        if len(v) != 6:
            raise ValueError("TOTP code must be exactly 6 digits")

        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "code": "123456",
                }
            ]
        }
    }


class TwoFactorDisable(BaseModel):
    """
    Schema for disabling two-factor authentication.

    Requires password confirmation for security.
    """

    password: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Current password for confirmation",
    )
    code: str = Field(
        ...,
        min_length=6,
        max_length=6,
        pattern=r"^\d{6}$",
        description="Current 6-digit TOTP code for verification",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "password": "SecureP@ssw0rd123!",
                    "code": "123456",
                }
            ]
        }
    }


class MessageResponse(BaseModel):
    """
    Generic message response schema.

    Used for simple success/error messages.
    """

    message: str = Field(..., description="Response message")
    detail: str | None = Field(None, description="Additional details (optional)")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "message": "Operation successful",
                    "detail": "Additional information here",
                }
            ]
        }
    }


class LoginSuccess(BaseModel):
    """
    Schema for successful login response.

    Includes user information and token type.
    Tokens are sent as HTTP-only cookies.
    """

    message: str = Field(default="Login successful", description="Success message")
    user: UserResponse = Field(..., description="User information")
    token_type: Literal["bearer"] = Field(
        default="bearer",
        description="Token type (always 'bearer')",
    )
    requires_2fa: bool = Field(
        default=False,
        description="Whether 2FA verification is required",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "message": "Login successful",
                    "user": {
                        "id": 1,
                        "username": "admin",
                        "is_active": True,
                        "is_superuser": True,
                        "totp_enabled": False,
                        "created_at": "2024-01-15T10:30:00Z",
                        "last_login": "2024-01-15T14:22:15Z",
                    },
                    "token_type": "bearer",
                    "requires_2fa": False,
                }
            ]
        }
    }


class PasswordChange(BaseModel):
    """
    Schema for password change request.

    Requires current password for security.
    """

    current_password: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Current password",
    )
    new_password: str = Field(
        ...,
        min_length=12,
        max_length=128,
        description="New password (minimum 12 characters)",
    )

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        """
        Validate new password strength.

        Uses same validation as UserRegister.

        Args:
            v: Password to validate

        Returns:
            str: Validated password

        Raises:
            ValueError: If password doesn't meet strength requirements
        """
        if len(v) < 12:
            raise ValueError("Password must be at least 12 characters long")

        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")

        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")

        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")

        if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-+=\[\]\\/'`~;]", v):
            raise ValueError("Password must contain at least one special character")

        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "current_password": "OldP@ssw0rd123!",
                    "new_password": "NewSecureP@ssw0rd456!",
                }
            ]
        }
    }
