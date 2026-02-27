"""
Rate limiting utilities for Splintarr.

Provides a proxy-aware key function for slowapi rate limiting that correctly
extracts client IP addresses when running behind a reverse proxy (production)
while preventing header spoofing in development/test environments.
"""

import structlog
from fastapi import Request

from splintarr.config import settings

logger = structlog.get_logger(__name__)


def rate_limit_key_func(request: Request) -> str:
    """
    Extract client IP address for rate limiting.

    In production (behind a reverse proxy), trusts the X-Forwarded-For header
    and returns the first IP (the original client IP set by the proxy).

    In development/test, uses request.client.host directly to prevent
    attackers from spoofing X-Forwarded-For to bypass rate limits.

    This function is designed to be used as slowapi's key_func parameter.

    Args:
        request: FastAPI/Starlette request object.

    Returns:
        Client IP address string, or "unknown" if it cannot be determined.
    """
    # Only trust X-Forwarded-For when behind a reverse proxy (production)
    # In development, attackers can spoof this header to bypass rate limiting
    if settings.environment == "production":
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # Take the first IP (client IP set by the reverse proxy)
            return forwarded.split(",")[0].strip()

    return request.client.host if request.client else "unknown"
