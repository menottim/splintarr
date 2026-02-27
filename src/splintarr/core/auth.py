"""
Core authentication logic for Splintarr.

This module provides JWT token management and two-factor authentication:
- Access token creation and validation (15-minute expiry)
- Refresh token creation, validation, and rotation (30-day expiry)
- Two-Factor Authentication (TOTP) using pyotp
- Helper functions for token extraction and user authentication
"""

import base64
import hmac
import io
import time
import uuid
from datetime import datetime, timedelta
from typing import Annotated, Any

import jwt
import pyotp
import qrcode
import structlog
from fastapi import Cookie, Depends, HTTPException, status
from jwt.exceptions import InvalidTokenError as JWTError
from sqlalchemy.orm import Session

from splintarr.config import settings
from splintarr.core.security import (
    DUMMY_PASSWORD_HASH,
    verify_password,
)
from splintarr.database import get_db
from splintarr.models.user import RefreshToken, User

logger = structlog.get_logger()

# JWT algorithm whitelist - NEVER accept 'none' or algorithms from config
# This prevents algorithm confusion attacks where attackers change algorithm
ALLOWED_JWT_ALGORITHMS = ["HS256"]

# In-memory access token blacklist for immediate revocation on logout (HIGH-02).
# Maps JTI -> expiry datetime. Auto-cleaned on each check.
# NOTE: Only works with a single worker process. For multi-worker, use Redis.
_access_token_blacklist: dict[str, datetime] = {}


def blacklist_access_token(token: str) -> None:
    """Add an access token's JTI to the blacklist (called on logout)."""
    try:
        payload = jwt.decode(token, settings.get_secret_key(), algorithms=ALLOWED_JWT_ALGORITHMS)
        jti = payload.get("jti")
        if jti:
            exp = payload.get("exp")
            expiry = (
                datetime.utcfromtimestamp(exp)
                if exp
                else datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
            )
            _access_token_blacklist[jti] = expiry
            logger.debug("access_token_blacklisted", jti=jti)
    except Exception as e:
        logger.warning("failed_to_blacklist_access_token", error=str(e))


def blacklist_2fa_pending_token(token: str) -> None:
    """Add a 2FA pending token's JTI to the blacklist (called after successful 2FA login).

    Prevents replay of the 2FA pending token within its 5-minute lifetime.
    Reuses the same in-memory blacklist as access tokens since the JTI
    namespace is globally unique (UUIDs) and cleanup logic is shared.
    """
    try:
        payload = jwt.decode(token, settings.get_secret_key(), algorithms=ALLOWED_JWT_ALGORITHMS)
        jti = payload.get("jti")
        if jti:
            exp = payload.get("exp")
            expiry = (
                datetime.utcfromtimestamp(exp)
                if exp
                else datetime.utcnow() + timedelta(minutes=5)
            )
            _access_token_blacklist[jti] = expiry
            logger.debug("2fa_pending_token_blacklisted", jti=jti)
    except Exception as e:
        logger.warning("failed_to_blacklist_2fa_pending_token", error=str(e))


def _cleanup_blacklist() -> None:
    """Remove expired entries from the access token blacklist."""
    now = datetime.utcnow()
    expired = [jti for jti, exp in _access_token_blacklist.items() if exp <= now]
    for jti in expired:
        del _access_token_blacklist[jti]


class AuthenticationError(Exception):
    """Exception raised when authentication fails."""

    pass


class TokenError(Exception):
    """Exception raised when token operations fail."""

    pass


class TwoFactorError(Exception):
    """Exception raised when 2FA operations fail."""

    pass


def create_access_token(
    user_id: int,
    username: str,
    additional_claims: dict[str, Any] | None = None,
) -> str:
    """
    Create a JWT access token.

    Access tokens are short-lived (15 minutes by default) and used for API authentication.
    They cannot be revoked, so keep the expiration time short.

    Args:
        user_id: User's database ID
        username: User's username
        additional_claims: Optional additional claims to include in token

    Returns:
        str: Signed JWT access token

    Raises:
        TokenError: If token creation fails
    """
    try:
        # Calculate expiration time
        expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
        expire = datetime.utcnow() + expires_delta

        # Build JWT claims
        claims: dict[str, Any] = {
            "sub": str(user_id),  # Subject: user ID
            "username": username,
            "type": "access",
            "exp": expire,  # Expiration time
            "iat": datetime.utcnow(),  # Issued at
            "jti": str(uuid.uuid4()),  # JWT ID (unique identifier)
        }

        # Add any additional claims (reject reserved claim names to prevent injection)
        if additional_claims:
            reserved_claims = {"sub", "exp", "iat", "jti", "type", "username"}
            injected = set(additional_claims.keys()) & reserved_claims
            if injected:
                raise TokenError(f"Cannot override reserved JWT claims: {', '.join(injected)}")
            claims.update(additional_claims)

        # Sign and encode token using hardcoded algorithm (prevent algorithm confusion)
        token = jwt.encode(
            claims,
            settings.get_secret_key(),
            algorithm=ALLOWED_JWT_ALGORITHMS[0],  # Use first allowed algorithm
        )

        logger.debug(
            "access_token_created",
            user_id=user_id,
            username=username,
            expires_in_minutes=settings.access_token_expire_minutes,
        )

        return token

    except Exception as e:
        logger.error("failed_to_create_access_token", user_id=user_id, error=str(e))
        raise TokenError(f"Failed to create access token: {e}") from e


def create_refresh_token(
    db: Session,
    user_id: int,
    device_info: str | None = None,
    ip_address: str | None = None,
) -> tuple[str, RefreshToken]:
    """
    Create a JWT refresh token and store it in the database.

    Refresh tokens are long-lived (30 days by default) and can be revoked.
    They are stored in the database to enable revocation and rotation.

    Args:
        db: Database session
        user_id: User's database ID
        device_info: Optional device/User-Agent information
        ip_address: Optional IP address where token was issued

    Returns:
        tuple[str, RefreshToken]: JWT token string and database record

    Raises:
        TokenError: If token creation or database operation fails
    """
    try:
        # Generate unique JWT ID
        jti = str(uuid.uuid4())

        # Calculate expiration time
        expires_delta = timedelta(days=settings.refresh_token_expire_days)
        expire = datetime.utcnow() + expires_delta

        # Build JWT claims
        claims: dict[str, Any] = {
            "sub": str(user_id),
            "type": "refresh",
            "jti": jti,
            "exp": expire,
            "iat": datetime.utcnow(),
        }

        # Sign and encode token using hardcoded algorithm (prevent algorithm confusion)
        token = jwt.encode(
            claims,
            settings.get_secret_key(),
            algorithm=ALLOWED_JWT_ALGORITHMS[0],  # Use first allowed algorithm
        )

        # Store token in database
        db_token = RefreshToken(
            jti=jti,
            user_id=user_id,
            expires_at=expire,
            device_info=device_info,
            ip_address=ip_address,
        )
        db.add(db_token)
        db.commit()
        db.refresh(db_token)

        logger.info(
            "refresh_token_created",
            user_id=user_id,
            jti=jti,
            expires_in_days=settings.refresh_token_expire_days,
        )

        return token, db_token

    except Exception as e:
        db.rollback()
        logger.error("failed_to_create_refresh_token", user_id=user_id, error=str(e))
        raise TokenError(f"Failed to create refresh token: {e}") from e


def verify_access_token(token: str) -> dict[str, Any]:
    """
    Verify and decode a JWT access token.

    Validates the token signature, expiration, and token type.
    Does not check database (access tokens cannot be revoked).

    Args:
        token: JWT access token to verify

    Returns:
        dict: Decoded token claims

    Raises:
        TokenError: If token is invalid, expired, or wrong type
    """
    try:
        # Decode and verify token with algorithm whitelist
        payload = jwt.decode(
            token,
            settings.get_secret_key(),
            algorithms=ALLOWED_JWT_ALGORITHMS,  # Hardcoded whitelist
        )

        # Explicitly verify the algorithm in the token header
        # This prevents algorithm confusion even if jwt.decode is compromised
        try:
            header = jwt.get_unverified_header(token)
            token_algorithm = header.get("alg")
            if token_algorithm not in ALLOWED_JWT_ALGORITHMS:
                raise TokenError(f"Invalid JWT algorithm: {token_algorithm}")
        except Exception as e:
            raise TokenError(f"Failed to verify token algorithm: {e}") from e

        # Verify token type
        if payload.get("type") != "access":
            raise TokenError("Invalid token type")

        # Check if token has been revoked via blacklist (HIGH-02)
        jti = payload.get("jti")
        if jti and jti in _access_token_blacklist:
            _cleanup_blacklist()
            if jti in _access_token_blacklist:
                logger.warning("access_token_blacklisted_rejected", jti=jti)
                raise TokenError("Token has been revoked")

        # Token is valid
        logger.debug("access_token_verified", user_id=payload.get("sub"))
        return payload

    except JWTError as e:
        logger.warning("access_token_verification_failed", error=str(e))
        raise TokenError(f"Invalid access token: {e}") from e


def verify_refresh_token(db: Session, token: str) -> tuple[dict[str, Any], RefreshToken]:
    """
    Verify and decode a JWT refresh token.

    Validates the token signature, expiration, token type, and checks
    the database to ensure the token hasn't been revoked.

    Args:
        db: Database session
        token: JWT refresh token to verify

    Returns:
        tuple[dict, RefreshToken]: Decoded claims and database record

    Raises:
        TokenError: If token is invalid, expired, revoked, or wrong type
    """
    try:
        # Decode and verify token with algorithm whitelist
        payload = jwt.decode(
            token,
            settings.get_secret_key(),
            algorithms=ALLOWED_JWT_ALGORITHMS,  # Hardcoded whitelist
        )

        # Explicitly verify the algorithm in the token header
        try:
            header = jwt.get_unverified_header(token)
            token_algorithm = header.get("alg")
            if token_algorithm not in ALLOWED_JWT_ALGORITHMS:
                raise TokenError(f"Invalid JWT algorithm: {token_algorithm}")
        except Exception as e:
            raise TokenError(f"Failed to verify token algorithm: {e}") from e

        # Verify token type
        if payload.get("type") != "refresh":
            raise TokenError("Invalid token type")

        # Get JTI from payload
        jti = payload.get("jti")
        if not jti:
            raise TokenError("Missing JTI in token")

        # Look up token in database
        db_token = db.query(RefreshToken).filter(RefreshToken.jti == jti).first()

        if not db_token:
            logger.warning("refresh_token_not_found", jti=jti)
            raise TokenError("Token not found in database")

        # Check if token is valid (not revoked and not expired)
        if not db_token.is_valid():
            logger.warning(
                "refresh_token_invalid",
                jti=jti,
                revoked=db_token.revoked,
                expired=db_token.is_expired(),
            )
            raise TokenError("Token has been revoked or expired")

        logger.debug("refresh_token_verified", jti=jti, user_id=db_token.user_id)
        return payload, db_token

    except JWTError as e:
        logger.warning("refresh_token_verification_failed", error=str(e))
        raise TokenError(f"Invalid refresh token: {e}") from e


def rotate_refresh_token(
    db: Session,
    old_token: str,
    device_info: str | None = None,
    ip_address: str | None = None,
) -> tuple[str, str, RefreshToken]:
    """
    Rotate a refresh token (revoke old, issue new).

    Token rotation improves security by limiting the lifetime of tokens
    and providing automatic revocation of old tokens.

    Args:
        db: Database session
        old_token: Current refresh token to rotate
        device_info: Optional device/User-Agent information
        ip_address: Optional IP address

    Returns:
        tuple[str, str, RefreshToken]: New access token, new refresh token, and database record

    Raises:
        TokenError: If old token is invalid or rotation fails
    """
    try:
        # Verify the old token
        payload, db_token = verify_refresh_token(db, old_token)

        # Get user ID from token
        user_id = int(payload["sub"])

        # Revoke the old token
        db_token.revoke()
        db.commit()

        logger.info("refresh_token_revoked_for_rotation", jti=db_token.jti, user_id=user_id)

        # Get user for access token
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise TokenError("User not found")

        # Create new tokens
        new_access_token = create_access_token(user.id, user.username)
        new_refresh_token, new_db_token = create_refresh_token(
            db=db,
            user_id=user.id,
            device_info=device_info,
            ip_address=ip_address,
        )

        logger.info(
            "tokens_rotated",
            user_id=user_id,
            old_jti=db_token.jti,
            new_jti=new_db_token.jti,
        )

        return new_access_token, new_refresh_token, new_db_token

    except Exception as e:
        db.rollback()
        logger.error("failed_to_rotate_tokens", error=str(e))
        raise TokenError(f"Failed to rotate tokens: {e}") from e


def revoke_refresh_token(db: Session, token: str) -> None:
    """
    Revoke a refresh token (logout).

    Marks the token as revoked in the database, preventing future use.

    Args:
        db: Database session
        token: Refresh token to revoke

    Raises:
        TokenError: If token is invalid or revocation fails
    """
    try:
        # Verify and get token from database
        payload, db_token = verify_refresh_token(db, token)

        # Revoke the token
        db_token.revoke()
        db.commit()

        logger.info("refresh_token_revoked", jti=db_token.jti, user_id=db_token.user_id)

    except Exception as e:
        db.rollback()
        logger.error("failed_to_revoke_token", error=str(e))
        raise TokenError(f"Failed to revoke token: {e}") from e


def revoke_all_user_tokens(db: Session, user_id: int) -> int:
    """
    Revoke all refresh tokens for a user.

    Useful for security events like password change or account compromise.

    Args:
        db: Database session
        user_id: User's database ID

    Returns:
        int: Number of tokens revoked

    Raises:
        TokenError: If revocation fails
    """
    try:
        now = datetime.utcnow()
        count = (
            db.query(RefreshToken)
            .filter(RefreshToken.user_id == user_id, RefreshToken.revoked == False)  # noqa: E712
            .update({"revoked": True, "revoked_at": now}, synchronize_session=False)
        )

        db.commit()

        logger.info("all_user_tokens_revoked", user_id=user_id, count=count)
        return count

    except Exception as e:
        db.rollback()
        logger.error("failed_to_revoke_all_tokens", user_id=user_id, error=str(e))
        raise TokenError(f"Failed to revoke all tokens: {e}") from e


def authenticate_user(
    db: Session,
    username: str,
    password: str,
    ip_address: str | None = None,
) -> User | None:
    """
    Authenticate a user with username and password.

    Handles account lockout, failed login tracking, and password verification.
    Uses constant-time comparison to prevent timing attacks.

    Args:
        db: Database session
        username: Username to authenticate
        password: Plain-text password to verify
        ip_address: Optional IP address for logging

    Returns:
        User | None: User object if authentication succeeds, None otherwise

    Raises:
        AuthenticationError: If account is locked or inactive
    """
    try:
        # Look up user by username
        user = db.query(User).filter(User.username == username).first()

        if not user:
            # Perform a dummy Argon2 verification to equalize response timing.
            # Without this, "user not found" returns in ~1ms while "wrong password"
            # takes ~500-2000ms (Argon2 computation), creating a timing oracle
            # that reveals whether a username exists (CRIT-01).
            verify_password("dummy", DUMMY_PASSWORD_HASH)
            logger.warning("authentication_failed_user_not_found", username=username)
            return None

        # Check if account is locked
        if user.is_locked():
            # Perform dummy verification to equalize timing with the password
            # check path, preventing attackers from distinguishing locked vs
            # unlocked accounts via response time.
            verify_password("dummy", DUMMY_PASSWORD_HASH)
            logger.warning(
                "authentication_failed_account_locked",
                username=username,
                locked_until=user.account_locked_until,
            )
            raise AuthenticationError("Account is temporarily locked due to failed login attempts")

        # Check if account is active
        if not user.is_active:
            logger.warning("authentication_failed_account_inactive", username=username)
            raise AuthenticationError("Account is inactive")

        # Verify password using constant-time comparison
        if not verify_password(password, user.password_hash):
            # Record failed login
            user.increment_failed_login(
                max_attempts=settings.max_failed_login_attempts,
                lockout_duration_minutes=settings.account_lockout_duration_minutes,
            )
            db.commit()

            logger.warning(
                "authentication_failed_invalid_password",
                username=username,
                failed_attempts=user.failed_login_attempts,
                ip_address=ip_address,
            )
            return None

        # Authentication successful
        user.record_successful_login(ip_address or "unknown")
        db.commit()

        logger.info(
            "authentication_successful",
            username=username,
            user_id=user.id,
            ip_address=ip_address,
        )

        return user

    except AuthenticationError:
        # Re-raise authentication errors
        raise
    except Exception as e:
        db.rollback()
        logger.error("authentication_error", username=username, error=str(e))
        raise AuthenticationError(f"Authentication failed: {e}") from e


# Two-Factor Authentication (TOTP) Functions


def generate_totp_secret() -> str:
    """
    Generate a new TOTP secret for two-factor authentication.

    Returns:
        str: Base32-encoded TOTP secret (32 characters)
    """
    secret = pyotp.random_base32()
    logger.debug("totp_secret_generated")
    return secret


def generate_totp_uri(secret: str, username: str) -> str:
    """
    Generate a TOTP provisioning URI for QR code generation.

    This URI can be encoded as a QR code for scanning with authenticator apps
    like Google Authenticator, Authy, or 1Password.

    Args:
        secret: Base32-encoded TOTP secret
        username: Username for the account

    Returns:
        str: otpauth:// URI for QR code generation
    """
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(
        name=username,
        issuer_name=settings.app_name,
    )
    logger.debug("totp_uri_generated", username=username)
    return uri


def verify_totp_code(
    secret: str,
    code: str,
    last_used_counter: int | None = None,
) -> tuple[bool, int | None]:
    """
    Verify a TOTP code against a secret with replay protection.

    Manually checks counters for offsets -1, 0, +1 (valid_window=1) using
    constant-time comparison, and rejects any code whose counter is not
    strictly greater than the last used counter.

    Args:
        secret: Base32-encoded TOTP secret
        code: 6-digit TOTP code from authenticator app
        last_used_counter: Counter value of last successfully used code (or None)

    Returns:
        tuple[bool, int | None]: (is_valid, matched_counter).
            matched_counter is set when is_valid is True.
    """
    try:
        totp = pyotp.TOTP(secret)
        current_counter = int(time.time()) // 30

        # Check offsets -1, 0, +1 (equivalent to valid_window=1)
        # Use constant-time comparison to prevent timing side-channels
        matched_counter: int | None = None
        for offset in (-1, 0, 1):
            candidate_counter = current_counter + offset
            expected_code = totp.at(candidate_counter * 30)
            if hmac.compare_digest(expected_code, code):
                matched_counter = candidate_counter
                break

        if matched_counter is None:
            logger.warning("totp_code_verification_failed")
            return False, None

        # Replay protection: reject if counter was already used or is older
        if last_used_counter is not None and matched_counter <= last_used_counter:
            logger.warning(
                "totp_code_replay_rejected",
                matched_counter=matched_counter,
                last_used_counter=last_used_counter,
            )
            return False, None

        logger.debug("totp_code_verified", counter=matched_counter)
        return True, matched_counter

    except Exception as e:
        logger.error("totp_verification_error", error=str(e))
        return False, None


def create_2fa_pending_token(user_id: int, username: str) -> str:
    """
    Create a short-lived JWT for 2FA-pending state.

    Issued after password verification succeeds for a 2FA-enabled user.
    Only accepted by the /api/auth/2fa/login-verify endpoint.

    Args:
        user_id: User's database ID
        username: User's username

    Returns:
        str: Signed JWT with type "2fa_pending" and 5-minute expiry
    """
    try:
        expire = datetime.utcnow() + timedelta(minutes=5)
        claims: dict[str, Any] = {
            "sub": str(user_id),
            "username": username,
            "type": "2fa_pending",
            "exp": expire,
            "iat": datetime.utcnow(),
            "jti": str(uuid.uuid4()),
        }
        token = jwt.encode(
            claims,
            settings.get_secret_key(),
            algorithm=ALLOWED_JWT_ALGORITHMS[0],
        )
        logger.debug("2fa_pending_token_created", user_id=user_id)
        return token
    except Exception as e:
        logger.error("failed_to_create_2fa_pending_token", user_id=user_id, error=str(e))
        raise TokenError(f"Failed to create 2FA pending token: {e}") from e


def verify_2fa_pending_token(token: str) -> dict[str, Any]:
    """
    Verify a 2FA-pending JWT token.

    Args:
        token: JWT token to verify

    Returns:
        dict: Decoded token claims

    Raises:
        TokenError: If token is invalid, expired, blacklisted, or not type "2fa_pending"
    """
    try:
        payload = jwt.decode(
            token,
            settings.get_secret_key(),
            algorithms=ALLOWED_JWT_ALGORITHMS,
        )
        if payload.get("type") != "2fa_pending":
            raise TokenError("Invalid token type")

        # Check if token has been blacklisted (replay protection)
        jti = payload.get("jti")
        if jti and jti in _access_token_blacklist:
            _cleanup_blacklist()
            if jti in _access_token_blacklist:
                logger.warning("2fa_pending_token_replay_rejected", jti=jti)
                raise TokenError("2FA pending token has already been used")

        logger.debug("2fa_pending_token_verified", user_id=payload.get("sub"))
        return payload
    except JWTError as e:
        logger.warning("2fa_pending_token_verification_failed", error=str(e))
        raise TokenError(f"Invalid 2FA pending token: {e}") from e


def generate_totp_qr_code_base64(uri: str) -> str:
    """
    Render a TOTP provisioning URI as a base64-encoded PNG data URI.

    Args:
        uri: otpauth:// URI to encode

    Returns:
        str: data:image/png;base64,... string for embedding in HTML
    """
    img = qrcode.make(uri)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    b64 = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def get_current_user_id_from_token(token: str) -> int:
    """
    Extract user ID from a JWT access token.

    Helper function for dependency injection in FastAPI endpoints.

    Args:
        token: JWT access token

    Returns:
        int: User ID from token

    Raises:
        TokenError: If token is invalid or missing user ID
    """
    try:
        payload = verify_access_token(token)
        user_id = payload.get("sub")

        if not user_id:
            raise TokenError("Missing user ID in token")

        return int(user_id)

    except ValueError as e:
        raise TokenError(f"Invalid user ID in token: {e}") from e


def cleanup_expired_tokens(db: Session) -> int:
    """
    Clean up expired refresh tokens from the database.

    Should be called periodically (e.g., daily) to remove old tokens.
    Only removes tokens that are already expired, not revoked tokens
    (those may be kept for audit purposes).

    Args:
        db: Database session

    Returns:
        int: Number of tokens deleted

    Raises:
        TokenError: If cleanup fails
    """
    try:
        # Delete expired tokens
        count = db.query(RefreshToken).filter(RefreshToken.expires_at < datetime.utcnow()).delete()

        db.commit()

        logger.info("expired_tokens_cleaned_up", count=count)
        return count

    except Exception as e:
        db.rollback()
        logger.error("failed_to_cleanup_expired_tokens", error=str(e))
        raise TokenError(f"Failed to cleanup expired tokens: {e}") from e


async def get_current_user_from_cookie(
    access_token: Annotated[str | None, Cookie()] = None,
    db: Session = Depends(get_db),
) -> User:
    """
    Get current user from access_token cookie.

    Used for dashboard pages and endpoints that require cookie-based authentication.

    Args:
        access_token: Access token from cookie
        db: Database session

    Returns:
        User: Current user object

    Raises:
        HTTPException: If not authenticated or user not found
    """
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    try:
        user_id = get_current_user_id_from_token(access_token)
        user = db.query(User).filter(User.id == user_id).first()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is inactive",
            )

        return user

    except TokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
        ) from e
