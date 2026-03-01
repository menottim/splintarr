"""
Splintarr FastAPI Application.

Main application entry point with:
- FastAPI app initialization
- Middleware configuration (CORS, rate limiting, security headers)
- Router registration
- Lifespan context manager (startup/shutdown)
- Database initialization
"""

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from splintarr.api import (
    auth,
    config,
    dashboard,
    exclusions,
    instances,
    library,
    notifications,
    search_history,
    search_queue,
)
from splintarr.config import settings
from splintarr.core.rate_limit import rate_limit_key_func
from splintarr.database import (
    close_db,
    database_health_check,
    get_session_factory,
    init_db,
    test_database_connection,
)
from splintarr.logging_config import configure_logging
from splintarr.services import start_scheduler, stop_scheduler
from splintarr.services.library_sync import get_sync_service

# Configure comprehensive logging system
configure_logging()
logger = structlog.get_logger(__name__)

# Initialize rate limiter
limiter = Limiter(
    key_func=rate_limit_key_func,
    default_limits=[f"{settings.rate_limit_per_minute}/minute"],
    storage_uri="memory://",  # WARNING: In-memory storage does not share state across workers.
    # With workers > 1, each worker has independent rate counters, effectively
    # multiplying the rate limit by the number of workers. For production with
    # multiple workers, use Redis: storage_uri="redis://localhost:6379"
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Application lifespan context manager.

    Handles startup (database init, scheduler start) and shutdown
    (scheduler stop, database close) in a single context manager,
    replacing the deprecated @app.on_event decorators.
    """
    # --- Startup ---
    try:
        logger.info(
            "application_starting",
            environment=settings.environment,
            log_level=settings.log_level,
        )

        # Initialize database
        init_db()
        logger.info("database_initialized")

        # Test database connection
        test_database_connection()
        logger.info("database_connection_verified")

        # Start search scheduler
        try:
            await start_scheduler(get_session_factory())
            logger.info("search_scheduler_started")
        except Exception as e:
            logger.error("search_scheduler_start_failed", error=str(e))
            # Don't fail startup if scheduler fails to start
            # This allows the app to run in read-only mode for troubleshooting

        # Initialize library sync service (singleton, no background job yet —
        # the APScheduler job is registered when the scheduler starts)
        try:
            get_sync_service(get_session_factory())
            logger.info("library_sync_service_ready")
        except Exception as e:
            logger.error("library_sync_init_failed", error=str(e))

        logger.info("application_started")

    except Exception as e:
        logger.error("application_startup_failed", error=str(e))
        raise

    yield

    # --- Shutdown ---
    try:
        logger.info("application_shutting_down")

        # Stop search scheduler
        try:
            await stop_scheduler()
            logger.info("search_scheduler_stopped")
        except Exception as e:
            logger.error("search_scheduler_stop_failed", error=str(e))

        # Close database connections
        close_db()
        logger.info("database_connections_closed")

        logger.info("application_shutdown_complete")

    except Exception as e:
        logger.error("application_shutdown_error", error=str(e))


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    description="Intelligent backlog search automation for Sonarr and Radarr (ALPHA - Not Hand-Verified)",
    version="0.2.0",
    docs_url="/api/docs" if settings.environment != "production" else None,
    redoc_url="/api/redoc" if settings.environment != "production" else None,
    openapi_url="/api/openapi.json" if settings.environment != "production" else None,
    lifespan=lifespan,
)

# Add rate limiter to app state
app.state.limiter = limiter

# Add rate limit exception handler
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Add SlowAPI middleware
app.add_middleware(SlowAPIMiddleware)

# Add CORS middleware
# CORS Security Configuration:
#   - allow_origins: Explicitly list allowed origins (no wildcards in production)
#   - allow_credentials: True for cookie-based authentication (requires explicit origins)
#   - allow_methods: Limited to necessary HTTP methods (no TRACE, CONNECT)
#   - allow_headers: "*" is safe here (browser sends, server validates)
#   - expose_headers: [] restricts response headers visible to JavaScript
#
# Security Notes:
#   1. NEVER use allow_origins=["*"] with allow_credentials=True (violates CORS spec)
#   2. Default origin is localhost:8000 - change CORS_ORIGINS env var for production
#   3. For production, use explicit domain: CORS_ORIGINS=["https://yourdomain.com"]
#   4. CORS is enforced by browsers - it's NOT a server-side security mechanism
#   5. API authentication (JWT, rate limiting) is the primary security layer
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
        allow_headers=["*"],
        expose_headers=[],
    )
    logger.info("cors_middleware_enabled", origins=settings.cors_origins)

# Add trusted host middleware (security)
if settings.environment == "production":
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.trusted_hosts,
    )
    logger.info("trusted_host_middleware_enabled", hosts=settings.trusted_hosts)


# Security headers middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """
    Add security headers to all responses.

    Implements OWASP recommendations:
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY
    - Strict-Transport-Security (HSTS) in production
    - Content-Security-Policy with nonce-based script protection
    - Permissions-Policy to disable unused browser features
    """
    # Generate a per-request CSP nonce for inline scripts
    # Templates access this via {{ request.state.csp_nonce }}
    nonce = secrets.token_urlsafe(16)
    request.state.csp_nonce = nonce

    try:
        response = await call_next(request)
    except Exception as exc:
        # BaseHTTPMiddleware.call_next() re-raises app exceptions even after
        # ExceptionMiddleware handles them, so we must catch here to return
        # a proper 500 response to the client.
        logger.error(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            error=str(exc),
            exc_info=True,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

    # Basic security headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    # HSTS (only in production with HTTPS)
    if settings.environment == "production" and settings.secure_cookies:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    # Content Security Policy with nonce-based script protection
    # Using nonces instead of 'unsafe-inline' to prevent XSS while allowing
    # inline scripts in templates. Each request gets a unique nonce.
    # Style 'unsafe-inline' is kept because Pico CSS requires it.
    csp_directives = [
        "default-src 'self'",
        f"script-src 'self' 'nonce-{nonce}'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: https:",
        "font-src 'self'",
        "connect-src 'self'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "object-src 'none'",
    ]
    response.headers["Content-Security-Policy"] = "; ".join(csp_directives)
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"

    return response


# Mount static files
app.mount("/static", StaticFiles(directory="src/splintarr/static"), name="static")

# Mount poster cache (served from data volume, created on first sync)
_poster_dir = Path("data/posters")
_poster_dir.mkdir(parents=True, exist_ok=True)
app.mount("/posters", StaticFiles(directory=str(_poster_dir)), name="posters")

# Include routers
app.include_router(dashboard.router)  # Dashboard router (includes root, setup, login)
app.include_router(auth.router)
app.include_router(instances.router)
app.include_router(search_queue.router)
app.include_router(search_history.router)
app.include_router(library.router)
app.include_router(notifications.router)
app.include_router(exclusions.router)
app.include_router(config.router)


# Root endpoint removed - handled by dashboard.router


@app.get("/health", tags=["health"])
async def health_check():
    """
    Health check endpoint.

    Returns application and database health status.
    """
    try:
        db_health = database_health_check()

        # Filter out sensitive details (cipher_version, pool internals)
        # before returning to unauthenticated callers (LOW-03).
        safe_db_health = {
            "status": db_health.get("status", "unknown"),
        }

        return {
            "status": "healthy" if db_health.get("status") == "healthy" else "unhealthy",
            "application": "operational",
            "database": safe_db_health,
        }

    except Exception as e:
        logger.error("health_check_failed", error=str(e))
        # Return generic error message - do not expose exception details
        # to unauthenticated callers (prevents information disclosure)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "application": "operational",
                "database": {"status": "unhealthy"},
            },
        )


@app.get("/api", tags=["api"])
async def api_info():
    """
    API information endpoint.

    Returns available API routes and authentication status.
    """
    return {
        "version": "v1",
        "endpoints": {
            "authentication": "/api/auth",
            "instances": "/api/instances",
            "search": "/api/search",
            "dashboard": "/api/dashboard",
        },
        "documentation": {
            "swagger": "/api/docs" if settings.environment != "production" else None,
            "redoc": "/api/redoc" if settings.environment != "production" else None,
        },
    }


def _sanitize_for_json(value: object) -> object:
    """Recursively convert non-JSON-serializable values (e.g. bytes) to strings."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {k: _sanitize_for_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_for_json(v) for v in value]
    return value


# Error handlers — tiered logging for all HTTP errors
@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Log validation errors at WARNING level."""
    logger.warning(
        "http_validation_error",
        path=request.url.path,
        method=request.method,
        errors=exc.errors(),
    )
    errors = []
    for error in exc.errors():
        # Ensure all values are JSON-serializable (bytes input causes TypeError).
        # Values can be nested dicts/lists, so sanitize recursively.
        sanitized = {k: _sanitize_for_json(v) for k, v in error.items()}
        errors.append(sanitized)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": errors},
    )


@app.exception_handler(HTTPException)
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Log HTTP exceptions — WARNING for 4xx, ERROR for 5xx."""
    if exc.status_code >= 500:
        logger.error(
            "http_server_error",
            path=request.url.path,
            method=request.method,
            status_code=exc.status_code,
            detail=str(exc.detail),
        )
    else:
        logger.warning(
            "http_client_error",
            path=request.url.path,
            method=request.method,
            status_code=exc.status_code,
            detail=str(exc.detail),
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for unhandled exceptions — always ERROR level."""
    logger.error(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "splintarr.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        log_level=settings.log_level.lower(),
        workers=settings.workers if not settings.reload else 1,
    )
