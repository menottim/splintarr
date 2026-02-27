"""
User and RefreshToken database models.

This module defines the User model for authentication and the RefreshToken model
for JWT refresh token tracking and revocation.
"""

from datetime import datetime, timedelta

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from splintarr.database import Base


class User(Base):
    """
    User model for authentication and authorization.

    Stores user credentials and tracks login attempts for security.
    Passwords are hashed using Argon2id with pepper (see core.security).
    """

    __tablename__ = "users"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Authentication
    username = Column(
        String(32),
        unique=True,
        nullable=False,
        index=True,
        comment="Unique username (alphanumeric and underscore only)",
    )
    password_hash = Column(
        String(255),
        nullable=False,
        comment="Argon2id password hash with per-user salt",
    )

    # Security - Failed login tracking
    failed_login_attempts = Column(
        Integer,
        default=0,
        nullable=False,
        comment="Count of consecutive failed login attempts",
    )
    account_locked_until = Column(
        DateTime,
        nullable=True,
        comment="Account lockout expiration timestamp (NULL if not locked)",
    )
    last_failed_login = Column(
        DateTime,
        nullable=True,
        comment="Timestamp of most recent failed login attempt",
    )

    # Security - Successful login tracking
    last_login = Column(
        DateTime,
        nullable=True,
        comment="Timestamp of most recent successful login",
    )
    last_login_ip = Column(
        String(45),
        nullable=True,
        comment="IP address of most recent successful login (IPv4 or IPv6)",
    )

    # Account status
    is_active = Column(
        Boolean,
        default=True,
        nullable=False,
        comment="Whether the account is active",
    )
    is_superuser = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="Whether the user has superuser privileges",
    )

    # Two-Factor Authentication (TOTP)
    totp_secret = Column(
        Text,
        nullable=True,
        comment="Fernet-encrypted TOTP secret for 2FA (NULL if disabled)",
    )
    totp_enabled = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="Whether two-factor authentication is enabled",
    )
    totp_last_used_counter = Column(
        Integer,
        nullable=True,
        comment="TOTP time-step counter of last used code (replay protection)",
    )

    # Timestamps
    created_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False,
        comment="Account creation timestamp",
    )
    updated_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="Last account update timestamp",
    )

    # Relationships
    refresh_tokens = relationship(
        "RefreshToken",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    instances = relationship(
        "Instance",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        """String representation of User."""
        return f"<User(id={self.id}, username='{self.username}', is_active={self.is_active})>"

    def is_locked(self) -> bool:
        """
        Check if the account is currently locked due to failed login attempts.

        Returns:
            bool: True if account is locked and lockout period has not expired
        """
        if not self.account_locked_until:
            return False

        # Check if lockout period has expired
        return datetime.utcnow() < self.account_locked_until

    def increment_failed_login(self, max_attempts: int, lockout_duration_minutes: int) -> None:
        """
        Increment failed login attempt counter and lock account if threshold exceeded.

        Uses exponential backoff for lockout duration to mitigate account lockout
        DoS attacks (MED-02) while still protecting against brute-force:
          - First lockout (5 attempts):  1 minute
          - Second tier (10 attempts):   5 minutes
          - Third tier (15 attempts):    15 minutes
          - Fourth tier (20+ attempts):  capped at lockout_duration_minutes

        Args:
            max_attempts: Failed attempts before first lockout
            lockout_duration_minutes: Maximum lockout duration in minutes (cap)
        """
        self.failed_login_attempts += 1
        self.last_failed_login = datetime.utcnow()

        # Lock account if max attempts exceeded, with escalating duration
        if self.failed_login_attempts >= max_attempts:
            excess = self.failed_login_attempts - max_attempts
            if excess < 5:
                duration = 1
            elif excess < 10:
                duration = 5
            elif excess < 15:
                duration = 15
            else:
                duration = min(lockout_duration_minutes, 30)

            self.account_locked_until = datetime.utcnow() + timedelta(minutes=duration)

    def reset_failed_login(self) -> None:
        """
        Reset failed login counter after successful authentication.

        Should be called after successful login to clear lockout state.
        """
        self.failed_login_attempts = 0
        self.account_locked_until = None
        self.last_failed_login = None

    def record_successful_login(self, ip_address: str) -> None:
        """
        Record a successful login.

        Args:
            ip_address: IP address of the client
        """
        self.last_login = datetime.utcnow()
        self.last_login_ip = ip_address
        self.reset_failed_login()


class RefreshToken(Base):
    """
    Refresh token model for JWT token rotation and revocation.

    Tracks issued refresh tokens to enable:
    - Token revocation (logout, security breach)
    - Token rotation (automatic refresh with new token)
    - Device/session tracking
    - Audit trail
    """

    __tablename__ = "refresh_tokens"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Token identification
    jti = Column(
        String(36),
        unique=True,
        nullable=False,
        index=True,
        comment="JWT ID (unique token identifier, typically UUID)",
    )

    # User relationship
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="User who owns this refresh token",
    )

    # Session tracking
    device_info = Column(
        String(255),
        nullable=True,
        comment="User-Agent string or device identifier",
    )
    ip_address = Column(
        String(45),
        nullable=True,
        comment="IP address where token was issued (IPv4 or IPv6)",
    )

    # Token lifecycle
    expires_at = Column(
        DateTime,
        nullable=False,
        index=True,
        comment="Token expiration timestamp",
    )
    revoked = Column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
        comment="Whether the token has been revoked",
    )
    revoked_at = Column(
        DateTime,
        nullable=True,
        comment="When the token was revoked (NULL if not revoked)",
    )

    # Timestamps
    created_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False,
        comment="Token creation timestamp",
    )

    # Relationships
    user = relationship("User", back_populates="refresh_tokens")

    def __repr__(self) -> str:
        """String representation of RefreshToken."""
        return (
            f"<RefreshToken(id={self.id}, jti='{self.jti}', "
            f"user_id={self.user_id}, revoked={self.revoked})>"
        )

    def is_valid(self) -> bool:
        """
        Check if the refresh token is still valid.

        A token is valid if:
        1. It has not been revoked
        2. It has not expired

        Returns:
            bool: True if token is valid and can be used
        """
        if self.revoked:
            return False

        if datetime.utcnow() >= self.expires_at:
            return False

        return True

    def revoke(self) -> None:
        """
        Revoke this refresh token.

        Should be called when:
        - User logs out
        - Token is rotated (old token is revoked, new token issued)
        - Security breach detected
        - Token is compromised
        """
        self.revoked = True
        self.revoked_at = datetime.utcnow()

    def is_expired(self) -> bool:
        """
        Check if the token has expired.

        Returns:
            bool: True if token expiration time has passed
        """
        return datetime.utcnow() >= self.expires_at

    @property
    def time_until_expiry(self) -> timedelta:
        """
        Calculate time remaining until token expiration.

        Returns:
            timedelta: Time remaining (negative if already expired)
        """
        return self.expires_at - datetime.utcnow()
