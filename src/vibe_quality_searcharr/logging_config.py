"""
Comprehensive logging configuration for Vibe-Quality-Searcharr.

This module provides a robust logging setup with:
- Multiple log levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- Log rotation to manage disk space
- Separate log files for different severity levels
- Console and file output
- Structured logging with JSON format for production
- Human-readable format for development
- Automatic PII/sensitive data filtering
"""

import logging
import logging.handlers
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from vibe_quality_searcharr.config import settings


def drop_color_message_key(_, __, event_dict: dict[str, Any]) -> dict[str, Any]:
    """
    Remove color-related keys from structlog events.

    Structlog adds these for console coloring but they shouldn't be in logs.
    """
    event_dict.pop("color_message", None)
    return event_dict


def censor_sensitive_data(_, __, event_dict: dict[str, Any]) -> dict[str, Any]:
    """
    Filter sensitive data from log messages.

    Censors common sensitive fields to prevent accidental logging of:
    - Passwords
    - API keys
    - Tokens
    - Secrets
    - Database keys
    """
    sensitive_keys = {
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "key",
        "db_key",
        "pepper",
    }

    for key, value in event_dict.items():
        # Check if key contains sensitive terms
        if any(sensitive in key.lower() for sensitive in sensitive_keys):
            if isinstance(value, str) and len(value) > 0:
                # Show first 4 chars for debugging, rest as asterisks
                event_dict[key] = f"{value[:4]}{'*' * (min(len(value) - 4, 8))}"

    return event_dict


def rotation_namer(default_name: str) -> str:
    """
    Custom namer for rotated log files using datetime stamps.

    Converts default rotation name (e.g., 'all.log.1') to datetime-based name
    (e.g., 'all-2026-02-24_143052.log').

    Args:
        default_name: Default rotated filename from RotatingFileHandler

    Returns:
        str: New filename with datetime stamp
    """
    # Extract directory, base name, and extension
    path = Path(default_name)
    dir_name = path.parent

    # Remove the numeric suffix (.1, .2, etc.) if present
    name_parts = path.stem.split(".")
    base_name = name_parts[0]  # e.g., 'all' from 'all.log.1'

    # Generate timestamp
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")

    # Create new filename: base-YYYY-MM-DD_HHMMSS.log
    new_name = f"{base_name}-{timestamp}.log"

    return str(dir_name / new_name)


def configure_logging() -> None:
    """
    Configure comprehensive application logging.

    Sets up:
    1. Console handler - Always enabled, respects LOG_LEVEL
    2. File handlers with rotation:
       - all.log - All messages (INFO and above by default)
       - error.log - Only ERROR and CRITICAL
       - debug.log - Everything (only created if LOG_LEVEL=DEBUG)

    Log rotation:
    - Max file size: 10 MB per file
    - Rotated files named with datetime: all-2026-02-24_143052.log
    - Backup count: 5 (keeps up to 5 old rotated files)
    - Total max space per log type: ~60 MB (1 current + 5 backups)

    Log levels:
    - DEBUG: Very verbose, includes all operations (use for troubleshooting)
    - INFO: Normal operations, user actions, key events (default)
    - WARNING: Unexpected but handled situations
    - ERROR: Errors that affect functionality
    - CRITICAL: Severe errors that may cause shutdown
    """
    # Create logs directory
    log_dir = Path("./logs")
    log_dir.mkdir(exist_ok=True)

    # Determine log level from settings
    log_level = getattr(logging, settings.log_level.upper())
    is_debug = settings.log_level.upper() == "DEBUG"
    is_production = settings.environment == "production"

    # Configure standard library logging first
    timestamper = structlog.processors.TimeStamper(fmt="iso")

    # Shared processors for both structlog and stdlib logging
    shared_processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        censor_sensitive_data,
        drop_color_message_key,
    ]

    # Setup handlers
    handlers = []

    # 1. Console Handler - Always enabled
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    if is_production:
        # Production: JSON format for easy parsing
        console_formatter = logging.Formatter(
            "%(message)s"  # structlog will handle formatting
        )
    else:
        # Development: Human-readable format with colors
        console_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    console_handler.setFormatter(console_formatter)
    handlers.append(console_handler)

    # 2. All logs file handler (INFO+ by default, DEBUG+ if debug mode)
    all_file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "all.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    all_file_handler.namer = rotation_namer  # Use datetime-based naming
    all_file_handler.setLevel(logging.DEBUG if is_debug else logging.INFO)
    all_file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    all_file_handler.setFormatter(all_file_formatter)
    handlers.append(all_file_handler)

    # 3. Error file handler (ERROR and CRITICAL only)
    error_file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "error.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    error_file_handler.namer = rotation_namer  # Use datetime-based naming
    error_file_handler.setLevel(logging.ERROR)
    error_file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s\n"
        "%(pathname)s:%(lineno)d\n"
        "%(message)s\n",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    error_file_handler.setFormatter(error_file_formatter)
    handlers.append(error_file_handler)

    # 4. Debug file handler (only in debug mode)
    if is_debug:
        debug_file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "debug.log",
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        debug_file_handler.namer = rotation_namer  # Use datetime-based naming
        debug_file_handler.setLevel(logging.DEBUG)
        debug_file_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s:%(funcName)s:%(lineno)d\n%(message)s\n",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        debug_file_handler.setFormatter(debug_file_formatter)
        handlers.append(debug_file_handler)

    # Configure root logger
    logging.basicConfig(
        format="%(message)s",
        level=log_level,
        handlers=handlers,
    )

    # Configure structlog
    structlog.configure(
        processors=shared_processors
        + [
            # Final rendering processor
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure processor formatter for stdlib integration
    formatter = structlog.stdlib.ProcessorFormatter(
        # Processor chain for logging output
        foreign_pre_chain=shared_processors,
        # Final rendering
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer()
            if is_production
            else structlog.dev.ConsoleRenderer(),
        ],
    )

    # Apply formatter to all handlers
    for handler in handlers:
        handler.setFormatter(formatter)

    # Reduce noise from verbose libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING if not is_debug else logging.INFO)
    logging.getLogger("apscheduler").setLevel(logging.WARNING if not is_debug else logging.INFO)

    # Log the logging configuration itself
    logger = structlog.get_logger(__name__)
    logger.info(
        "logging_configured",
        log_level=settings.log_level,
        environment=settings.environment,
        log_dir=str(log_dir.absolute()),
        handlers={
            "console": True,
            "all_log": True,
            "error_log": True,
            "debug_log": is_debug,
        },
        rotation={
            "max_bytes": "10 MB",
            "backup_count": 5,
            "total_max_per_log": "~50 MB",
        },
    )


def get_log_info() -> dict[str, Any]:
    """
    Get current logging configuration information.

    Returns:
        dict: Logging configuration details including:
            - log_level: Current log level
            - log_dir: Path to log directory
            - log_files: List of existing log files with sizes
            - total_size: Total size of all log files
    """
    log_dir = Path("./logs")

    if not log_dir.exists():
        return {
            "log_level": settings.log_level,
            "log_dir": str(log_dir.absolute()),
            "log_files": [],
            "total_size": 0,
        }

    log_files = []
    total_size = 0

    for log_file in log_dir.glob("*.log*"):
        size = log_file.stat().st_size
        total_size += size
        log_files.append(
            {
                "name": log_file.name,
                "size_bytes": size,
                "size_mb": round(size / (1024 * 1024), 2),
            }
        )

    return {
        "log_level": settings.log_level,
        "log_dir": str(log_dir.absolute()),
        "log_files": sorted(log_files, key=lambda x: x["name"]),
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / (1024 * 1024), 2),
    }
