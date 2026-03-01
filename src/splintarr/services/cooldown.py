"""Tiered cooldown logic for search items."""

from datetime import datetime, timedelta
from typing import Any

import structlog

logger = structlog.get_logger()

# Adaptive cooldown tiers: (max_item_age, base_cooldown_hours)
ADAPTIVE_TIERS: list[tuple[timedelta | None, int]] = [
    (timedelta(hours=24), 6),
    (timedelta(days=7), 12),
    (timedelta(days=30), 24),
    (timedelta(days=365), 72),
    (None, 168),  # 7 days for items >1 year old
]

MAX_COOLDOWN_HOURS = 336  # 14 days cap


def is_in_cooldown(
    library_item: Any | None,
    record: dict[str, Any],
    cooldown_mode: str,
    cooldown_hours: int | None,
) -> bool:
    """Check if an item should be skipped due to cooldown.

    Args:
        library_item: LibraryItem from DB (None if not synced)
        record: Item dict from *arr API (has airDateUtc/added)
        cooldown_mode: 'adaptive' or 'flat'
        cooldown_hours: Fixed cooldown hours (when mode='flat')
    """
    if library_item is None or library_item.last_searched_at is None:
        return False  # Never searched -> not in cooldown

    if cooldown_mode == "flat":
        hours = cooldown_hours or 24
        return _check_cooldown(library_item.last_searched_at, hours)

    # Adaptive mode
    base_hours = _get_base_cooldown(record)
    failures = getattr(library_item, "consecutive_failures", 0)
    if failures > 0:
        backoff_hours = base_hours * (2 ** min(failures, 8))
        effective_hours = min(backoff_hours, MAX_COOLDOWN_HOURS)
    else:
        effective_hours = base_hours

    return _check_cooldown(library_item.last_searched_at, effective_hours)


def get_effective_cooldown_hours(
    library_item: Any | None,
    record: dict[str, Any],
    cooldown_mode: str,
    cooldown_hours: int | None,
) -> int:
    """Get the effective cooldown in hours for an item (for logging/display)."""
    if cooldown_mode == "flat":
        return cooldown_hours or 24

    base_hours = _get_base_cooldown(record)
    failures = getattr(library_item, "consecutive_failures", 0) if library_item else 0
    if failures > 0:
        return min(base_hours * (2 ** min(failures, 8)), MAX_COOLDOWN_HOURS)
    return base_hours


def _check_cooldown(last_searched: datetime, hours: int) -> bool:
    cooldown_until = last_searched + timedelta(hours=hours)
    return datetime.utcnow() < cooldown_until


def _get_base_cooldown(record: dict[str, Any]) -> int:
    date_str = record.get("airDateUtc") or record.get("added")
    if not date_str:
        return 24

    try:
        if isinstance(date_str, str):
            item_date = datetime.fromisoformat(date_str.replace("Z", "+00:00")).replace(tzinfo=None)
        else:
            item_date = date_str
    except (ValueError, TypeError):
        return 24

    age = datetime.utcnow() - item_date
    for max_age, hours in ADAPTIVE_TIERS:
        if max_age is None or age < max_age:
            return hours
    return 168
