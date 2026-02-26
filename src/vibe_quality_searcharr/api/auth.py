"""
Authentication API endpoints for Vibe-Quality-Searcharr.

This module provides REST API endpoints for:
- User registration (first-run only)
- Login with username/password
- Logout (token revocation)
- Token refresh (rotation)
- Two-factor authentication (TOTP) setup and verification

All endpoints use HTTP-only, Secure, SameSite cookies for tokens.
Rate limiting is applied to prevent brute-force attacks.
"""

from typing import Annotated

import structlog
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from vibe_quality_searcharr.config import settings
from vibe_quality_searcharr.core.auth import (
    AuthenticationError,
    TokenError,
    authenticate_user,
    blacklist_access_token,
    create_2fa_pending_token,
    create_access_token,
    create_refresh_token,
    generate_totp_qr_code_base64,
    generate_totp_secret,
    generate_totp_uri,
    get_current_user_id_from_token,
    revoke_all_user_tokens,
    revoke_refresh_token,
    rotate_refresh_token,
    verify_2fa_pending_token,
    verify_totp_code,
)
from vibe_quality_searcharr.core.security import hash_password, verify_password
from vibe_quality_searcharr.database import get_db
from vibe_quality_searcharr.models.user import User
from vibe_quality_searcharr.schemas.user import (
    LoginSuccess,
    MessageResponse,
    PasswordChange,
    TwoFactorDisable,
    TwoFactorSetup,
    TwoFactorVerify,
    UserLogin,
    UserRegister,
    UserResponse,
)

logger = structlog.get_logger()

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

# Create router
router = APIRouter(
    prefix="/api/auth",
    tags=["authentication"],
)


def get_client_ip(request: Request) -> str:
    """
    Extract client IP address from request.

    Only trusts X-Forwarded-For in production (where a reverse proxy is expected).
    In development/test, uses the direct client IP to prevent spoofing.

    Args:
        request: FastAPI request object

    Returns:
        str: Client IP address
    """
    # Only trust X-Forwarded-For when behind a reverse proxy (production)
    # In development, attackers can spoof this header to bypass rate limiting
    if settings.environment == "production":
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # Take the first IP (client IP set by the reverse proxy)
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: str,
) -> None:
    """
    Set authentication cookies on response.

    Cookies are:
    - HTTP-only (not accessible to JavaScript)
    - Secure (only sent over HTTPS in production)
    - SameSite=Lax (CSRF protection)

    Args:
        response: FastAPI response object
        access_token: JWT access token
        refresh_token: JWT refresh token
    """
    # Access token cookie (15 minutes)
    # NOTE (MED-05): path="/" means this cookie is sent with all requests including
    # static files. A more restrictive path is not feasible because the cookie is
    # needed on /dashboard, /setup, /login, and /api -- which share no common prefix
    # other than "/". The cookie is HttpOnly and SameSite=Strict, minimizing exposure.
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )

    # Refresh token cookie (30 days)
    # Using SameSite=Strict for CSRF protection
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",  # Changed from 'lax' to 'strict' for CSRF protection
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        path="/api/auth",  # Only send to auth endpoints
    )

    logger.debug("auth_cookies_set")


def clear_auth_cookies(response: Response) -> None:
    """
    Clear authentication cookies on logout.

    Args:
        response: FastAPI response object
    """
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="refresh_token", path="/api/auth")
    logger.debug("auth_cookies_cleared")


async def get_current_user(
    access_token: Annotated[str | None, Cookie()] = None,
    db: Session = Depends(get_db),
) -> User:
    """
    Get current authenticated user from access_token cookie.

    This dependency function is used by API endpoints that require authentication.
    For dashboard/web pages, use get_current_user_from_cookie in dashboard.py.

    Args:
        access_token: Access token from cookie
        db: Database session

    Returns:
        User: Current user object

    Raises:
        HTTPException: If not authenticated, user not found, or account inactive
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


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register first user",
    description="Register the first user (first-run only). Only available when no users exist.",
)
@limiter.limit("3/hour")
async def register(
    user_data: UserRegister,
    request: Request,
    db: Session = Depends(get_db),
) -> UserResponse:
    """
    Register the first user.

    Only available during first-run when no users exist.
    After the first user is created, this endpoint returns 403 Forbidden.

    **Rate Limit:** 3 requests per hour per IP

    Args:
        user_data: User registration data
        request: FastAPI request object
        db: Database session

    Returns:
        UserResponse: Created user information

    Raises:
        HTTPException:
            - 400: Username already exists
            - 403: Registration disabled (users already exist)
            - 500: Server error during registration
    """
    try:
        # Check if any users exist
        user_count = db.query(User).count()
        if user_count > 0:
            logger.warning(
                "registration_attempt_rejected",
                reason="users_exist",
                ip=get_client_ip(request),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Registration is disabled. Users already exist.",
            )

        # Check if username already exists (shouldn't happen, but validate anyway)
        existing_user = db.query(User).filter(User.username == user_data.username).first()
        if existing_user:
            logger.warning(
                "registration_failed_username_exists",
                username=user_data.username,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already exists",
            )

        # Hash password
        password_hash = hash_password(user_data.password)

        # Create user
        user = User(
            username=user_data.username,
            password_hash=password_hash,
            is_active=True,
            is_superuser=True,  # First user is always superuser
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        logger.info(
            "user_registered",
            user_id=user.id,
            username=user.username,
            ip=get_client_ip(request),
        )

        # Convert to response model
        return UserResponse(
            id=user.id,
            username=user.username,
            is_active=user.is_active,
            is_superuser=user.is_superuser,
            totp_enabled=user.totp_enabled,
            created_at=user.created_at.isoformat(),
            last_login=user.last_login.isoformat() if user.last_login else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error("registration_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to register user",
        ) from e


@router.post(
    "/login",
    response_model=LoginSuccess,
    summary="Login with username and password",
    description="Authenticate user and receive access/refresh tokens as HTTP-only cookies.",
)
@limiter.limit("5/minute")
async def login(
    user_data: UserLogin,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> LoginSuccess:
    """
    Authenticate user with username and password.

    Returns tokens as HTTP-only cookies for security.
    Implements account lockout after failed attempts.

    **Rate Limit:** 5 requests per minute per IP

    Args:
        user_data: User login credentials
        request: FastAPI request object
        response: FastAPI response object
        db: Database session

    Returns:
        LoginSuccess: User information and token type

    Raises:
        HTTPException:
            - 401: Invalid credentials or account locked
            - 500: Server error during login
    """
    try:
        # Get client IP
        ip_address = get_client_ip(request)

        # Authenticate user
        try:
            user = authenticate_user(db, user_data.username, user_data.password, ip_address)
        except AuthenticationError as e:
            # Use generic error message to prevent account enumeration
            # Specific error is logged for debugging (see authenticate_user logs)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
            ) from e

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
            )

        # Check if 2FA is enabled for this user
        if user.totp_enabled:
            # Issue a restricted 2FA pending token instead of full tokens
            pending_token = create_2fa_pending_token(user.id, user.username)
            response.set_cookie(
                key="2fa_pending_token",
                value=pending_token,
                httponly=True,
                secure=settings.secure_cookies,
                samesite="strict",
                max_age=300,  # 5 minutes
                path="/",
            )

            logger.info(
                "login_requires_2fa",
                user_id=user.id,
                username=user.username,
                ip=ip_address,
            )

            return LoginSuccess(
                message="2FA verification required",
                user=UserResponse(
                    id=user.id,
                    username=user.username,
                    is_active=user.is_active,
                    is_superuser=user.is_superuser,
                    totp_enabled=user.totp_enabled,
                    created_at=user.created_at.isoformat(),
                    last_login=user.last_login.isoformat() if user.last_login else None,
                ),
                token_type="bearer",
                requires_2fa=True,
            )

        # No 2FA — issue full tokens
        access_token = create_access_token(user.id, user.username)
        user_agent = request.headers.get("User-Agent", "unknown")
        refresh_token, _ = create_refresh_token(
            db=db,
            user_id=user.id,
            device_info=user_agent,
            ip_address=ip_address,
        )

        # Set cookies
        set_auth_cookies(response, access_token, refresh_token)

        logger.info(
            "user_logged_in",
            user_id=user.id,
            username=user.username,
            ip=ip_address,
        )

        # Return user information
        return LoginSuccess(
            message="Login successful",
            user=UserResponse(
                id=user.id,
                username=user.username,
                is_active=user.is_active,
                is_superuser=user.is_superuser,
                totp_enabled=user.totp_enabled,
                created_at=user.created_at.isoformat(),
                last_login=user.last_login.isoformat() if user.last_login else None,
            ),
            token_type="bearer",
            requires_2fa=False,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("login_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed",
        ) from e


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Logout and revoke refresh token",
    description="Revoke refresh token and clear authentication cookies.",
)
async def logout(
    request: Request,
    response: Response,
    refresh_token: Annotated[str | None, Cookie()] = None,
    db: Session = Depends(get_db),
) -> MessageResponse:
    """
    Logout user and revoke refresh token.

    Clears authentication cookies, blacklists the access token for immediate
    revocation (HIGH-02), and marks refresh token as revoked.

    Args:
        request: FastAPI request object
        response: FastAPI response object
        refresh_token: Refresh token from cookie
        db: Database session

    Returns:
        MessageResponse: Logout success message

    Raises:
        HTTPException:
            - 500: Server error during logout
    """
    try:
        # Blacklist current access token for immediate revocation (HIGH-02)
        access_token_value = request.cookies.get("access_token")
        if access_token_value:
            blacklist_access_token(access_token_value)

        # Clear cookies (always do this, even if token is invalid)
        clear_auth_cookies(response)

        # If no refresh token, still return success (already logged out)
        if not refresh_token:
            logger.debug("logout_no_token")
            return MessageResponse(message="Logged out successfully")

        # Revoke refresh token in database
        try:
            revoke_refresh_token(db, refresh_token)
            logger.info("user_logged_out")
        except TokenError as e:
            # Token already invalid, but we cleared cookies so logout is successful
            logger.warning("logout_invalid_token", error=str(e))

        return MessageResponse(message="Logged out successfully")

    except Exception as e:
        logger.error("logout_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Logout failed",
        ) from e


@router.post(
    "/refresh",
    response_model=MessageResponse,
    summary="Refresh access token",
    description="Rotate refresh token and get new access/refresh tokens.",
)
@limiter.limit("10/minute")
async def refresh(
    request: Request,
    response: Response,
    refresh_token: Annotated[str | None, Cookie()] = None,
    db: Session = Depends(get_db),
) -> MessageResponse:
    """
    Refresh access token using refresh token.

    Implements token rotation: old refresh token is revoked,
    new access and refresh tokens are issued.

    **Rate Limit:** 10 requests per minute per IP

    Args:
        request: FastAPI request object
        response: FastAPI response object
        refresh_token: Refresh token from cookie
        db: Database session

    Returns:
        MessageResponse: Success message

    Raises:
        HTTPException:
            - 401: No refresh token or invalid token
            - 500: Server error during refresh
    """
    try:
        if not refresh_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="No refresh token provided",
            )

        # Get device info
        user_agent = request.headers.get("User-Agent", "unknown")
        ip_address = get_client_ip(request)

        # Rotate tokens
        try:
            new_access_token, new_refresh_token, _ = rotate_refresh_token(
                db=db,
                old_token=refresh_token,
                device_info=user_agent,
                ip_address=ip_address,
            )
        except TokenError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication failed",
            ) from e

        # Set new cookies
        set_auth_cookies(response, new_access_token, new_refresh_token)

        logger.info("tokens_refreshed", ip=ip_address)

        return MessageResponse(message="Tokens refreshed successfully")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("token_refresh_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to refresh tokens",
        ) from e


# Two-Factor Authentication (TOTP) endpoints


@router.post(
    "/2fa/setup",
    response_model=TwoFactorSetup,
    summary="Setup two-factor authentication",
    description="Generate TOTP secret and QR code for 2FA setup. Requires authentication.",
)
async def setup_2fa(
    access_token: Annotated[str | None, Cookie()] = None,
    db: Session = Depends(get_db),
) -> TwoFactorSetup:
    """
    Begin 2FA setup by generating a TOTP secret and QR code.

    The secret is stored on the user but 2FA is NOT enabled until verification.

    **Authentication Required:** Access token cookie
    """
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    try:
        user_id = get_current_user_id_from_token(access_token)
    except TokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
        ) from e

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA is already enabled",
        )

    # Generate and store secret (not yet enabled)
    secret = generate_totp_secret()
    user.totp_secret = secret
    db.commit()

    uri = generate_totp_uri(secret, user.username)
    qr_data_uri = generate_totp_qr_code_base64(uri)

    logger.info("2fa_setup_initiated", user_id=user.id)

    return TwoFactorSetup(
        secret=secret,
        qr_code_uri=uri,
        qr_code_data_uri=qr_data_uri,
    )


@router.post(
    "/2fa/verify",
    response_model=MessageResponse,
    summary="Verify and enable two-factor authentication",
    description="Verify a TOTP code to complete 2FA setup. Requires authentication.",
)
async def verify_2fa(
    verify_data: TwoFactorVerify,
    access_token: Annotated[str | None, Cookie()] = None,
    db: Session = Depends(get_db),
) -> MessageResponse:
    """
    Complete 2FA setup by verifying a TOTP code from the authenticator app.

    **Authentication Required:** Access token cookie
    """
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    try:
        user_id = get_current_user_id_from_token(access_token)
    except TokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
        ) from e

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA is already enabled",
        )

    if not user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA setup not initiated. Call /2fa/setup first.",
        )

    if not verify_totp_code(user.totp_secret, verify_data.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid TOTP code",
        )

    # Enable 2FA
    user.totp_enabled = True
    db.commit()

    logger.info("2fa_enabled", user_id=user.id)

    return MessageResponse(message="Two-factor authentication enabled successfully")


@router.post(
    "/2fa/login-verify",
    response_model=LoginSuccess,
    summary="Complete login with TOTP code",
    description="Verify TOTP code after password authentication for 2FA-enabled accounts.",
)
@limiter.limit("5/minute")
async def login_verify_2fa(
    verify_data: TwoFactorVerify,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> LoginSuccess:
    """
    Complete 2FA login by verifying the TOTP code.

    Reads the 2FA pending token from cookie, verifies the TOTP code,
    and issues full access + refresh tokens.

    **Rate Limit:** 5 requests per minute per IP
    """
    pending_token = request.cookies.get("2fa_pending_token")
    if not pending_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No 2FA pending session",
        )

    try:
        payload = verify_2fa_pending_token(pending_token)
    except TokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="2FA session expired or invalid",
        ) from e

    user_id = int(payload["sub"])
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
        )

    if not user.totp_secret or not user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA is not enabled for this account",
        )

    if not verify_totp_code(user.totp_secret, verify_data.code):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid TOTP code",
        )

    # 2FA passed — issue full tokens
    ip_address = get_client_ip(request)
    access_token = create_access_token(user.id, user.username)
    user_agent = request.headers.get("User-Agent", "unknown")
    refresh_token, _ = create_refresh_token(
        db=db,
        user_id=user.id,
        device_info=user_agent,
        ip_address=ip_address,
    )

    set_auth_cookies(response, access_token, refresh_token)

    # Clear the pending token cookie
    response.delete_cookie(key="2fa_pending_token", path="/")

    logger.info(
        "user_logged_in_with_2fa",
        user_id=user.id,
        username=user.username,
        ip=ip_address,
    )

    return LoginSuccess(
        message="Login successful",
        user=UserResponse(
            id=user.id,
            username=user.username,
            is_active=user.is_active,
            is_superuser=user.is_superuser,
            totp_enabled=user.totp_enabled,
            created_at=user.created_at.isoformat(),
            last_login=user.last_login.isoformat() if user.last_login else None,
        ),
        token_type="bearer",
        requires_2fa=False,
    )


@router.post(
    "/2fa/disable",
    response_model=MessageResponse,
    summary="Disable two-factor authentication",
    description="Disable 2FA. Requires password and current TOTP code.",
)
async def disable_2fa(
    disable_data: TwoFactorDisable,
    access_token: Annotated[str | None, Cookie()] = None,
    db: Session = Depends(get_db),
) -> MessageResponse:
    """
    Disable 2FA for the current user.

    Requires password and valid TOTP code for security.

    **Authentication Required:** Access token cookie
    """
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    try:
        user_id = get_current_user_id_from_token(access_token)
    except TokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
        ) from e

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if not user.totp_enabled or not user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA is not enabled",
        )

    # Verify password
    if not verify_password(disable_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password",
        )

    # Verify TOTP code
    if not verify_totp_code(user.totp_secret, disable_data.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid TOTP code",
        )

    # Clear secret and disable
    user.totp_secret = None
    user.totp_enabled = False
    db.commit()

    logger.info("2fa_disabled", user_id=user.id)

    return MessageResponse(message="Two-factor authentication disabled successfully")


@router.post(
    "/password/change",
    response_model=MessageResponse,
    summary="Change password",
    description="Change user password (requires current password).",
)
@limiter.limit("3/minute")
async def change_password(
    request: Request,
    password_data: PasswordChange,
    access_token: Annotated[str | None, Cookie()] = None,
    db: Session = Depends(get_db),
) -> MessageResponse:
    """
    Change user password.

    Requires current password for security.
    Revokes all refresh tokens after password change.

    **Authentication Required:** Access token cookie

    Args:
        password_data: Current and new password
        access_token: Access token from cookie
        db: Database session

    Returns:
        MessageResponse: Success message

    Raises:
        HTTPException:
            - 401: Not authenticated or invalid current password
            - 404: User not found
            - 500: Server error during password change
    """
    try:
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
            )

        try:
            user_id = get_current_user_id_from_token(access_token)
        except TokenError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication failed",
            ) from e

        # Get user from database
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        # Verify current password
        if not verify_password(password_data.current_password, user.password_hash):
            logger.warning("password_change_failed_invalid_current", user_id=user.id)
            # Use generic error message to prevent information disclosure
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Password change failed",
            )

        # Hash new password
        new_password_hash = hash_password(password_data.new_password)

        # Update password
        user.password_hash = new_password_hash
        db.commit()

        # Revoke all refresh tokens (force re-login on all devices)
        revoke_all_user_tokens(db, user.id)

        logger.info("password_changed", user_id=user.id)

        return MessageResponse(
            message="Password changed successfully",
            detail="All sessions have been logged out. Please login again.",
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error("password_change_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to change password",
        ) from e
