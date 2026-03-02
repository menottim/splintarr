"""
Shared Jinja2 template configuration and custom filters for Splintarr.

Provides a single Jinja2Templates instance with all custom filters registered.
Import `templates` from this module instead of creating per-router instances.
"""

import json
from datetime import datetime
from typing import Any

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="src/splintarr/templates")


def _timeago(dt: datetime) -> str:
    """Format datetime as time ago (e.g., '2 hours ago')."""
    if not dt:
        return ""
    seconds = (datetime.utcnow() - dt).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        minutes = int(seconds / 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    if seconds < 86400:
        hours = int(seconds / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    if seconds < 604800:
        days = int(seconds / 86400)
        return f"{days} day{'s' if days != 1 else ''} ago"
    return dt.strftime("%Y-%m-%d")


def _parse_search_log(value: str | None) -> list[dict[str, Any]]:
    """Parse JSON search_metadata into a list of log entries for template rendering.

    Each entry may contain: item, action, result, reason, error,
    score, score_reason, grab_confirmed.
    """
    if not value:
        return []
    try:
        data = json.loads(value)
        if not isinstance(data, list):
            return []
        return [entry for entry in data if isinstance(entry, dict)]
    except (json.JSONDecodeError, TypeError):
        return []


# Register custom filters
templates.env.filters["datetime"] = lambda value: (
    value.strftime("%Y-%m-%d %H:%M:%S UTC") if value else ""
)
templates.env.filters["timeago"] = lambda value: _timeago(value) if value else ""
templates.env.filters["parse_search_log"] = lambda value: _parse_search_log(value)
