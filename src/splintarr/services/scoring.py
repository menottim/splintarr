"""
Scoring engine for intelligent search queue prioritization.

Computes a 0-100 priority score for each wanted item by combining three
weighted factors: recency (how recently the content aired/was added),
attempts (how many times Splintarr has already searched for it), and
staleness (how long since the last search attempt).

Strategy presets let different queue types emphasize different factors:
- "missing" favors recency (new content is more likely to be available)
- "cutoff_unmet" favors staleness (upgrades benefit from waiting)
- "recent" heavily favors recency (time-sensitive content)
"""

from datetime import datetime, timedelta
from typing import Any

import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Strategy weight tables
# ---------------------------------------------------------------------------
STRATEGY_WEIGHTS: dict[str, dict[str, float]] = {
    "missing": {"recency": 1.5, "attempts": 0.8, "staleness": 0.7},
    "cutoff_unmet": {"recency": 0.7, "attempts": 0.8, "staleness": 1.5},
    "recent": {"recency": 2.0, "attempts": 0.5, "staleness": 0.5},
}

DEFAULT_WEIGHTS: dict[str, float] = {"recency": 1.0, "attempts": 1.0, "staleness": 1.0}

# Maximum raw scores for each factor
MAX_RECENCY = 40
MAX_ATTEMPTS = 30
MAX_STALENESS = 30


# ---------------------------------------------------------------------------
# Date parsing helper
# ---------------------------------------------------------------------------
def _parse_date(date_str: str | None) -> datetime | None:
    """Parse an ISO 8601 date string from Sonarr/Radarr APIs.

    Handles the trailing "Z" that Python's fromisoformat doesn't accept
    before 3.11. Returns None on any parse failure.
    """
    if date_str is None:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, TypeError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Factor calculators
# ---------------------------------------------------------------------------
def _recency_score(record: dict[str, Any]) -> int:
    """Score 0-40 based on how recently the content aired or was added.

    Uses ``airDateUtc`` (Sonarr episodes) falling back to ``added``
    (Radarr movies). Returns a middle-ground score when no date is
    available.
    """
    date_str = record.get("airDateUtc") or record.get("added")
    dt = _parse_date(date_str)

    if dt is None:
        return 15  # Unknown / unparseable → middle ground

    now = datetime.utcnow()
    age = now - dt

    if age < timedelta(0):
        return 5  # Future air date — not yet available on indexers

    if age < timedelta(hours=24):
        return 40
    if age < timedelta(days=7):
        return 30
    if age < timedelta(days=30):
        return 20
    if age < timedelta(days=365):
        return 10
    return 5


def _attempts_score(library_item: Any | None) -> int:
    """Score 0-30 based on how many search attempts have been made.

    Fewer attempts → higher score (never-searched items are prioritized).
    A ``None`` library_item is treated as never searched.
    """
    if library_item is None:
        return 30

    attempts: int = library_item.search_attempts or 0

    if attempts == 0:
        return 30
    if attempts <= 5:
        return 25
    if attempts <= 10:
        return 15
    if attempts <= 20:
        return 8
    return 2


def _staleness_score(library_item: Any | None) -> int:
    """Score 0-30 based on time elapsed since last search attempt.

    Longer since last search → higher score (stale items need attention).
    A ``None`` library_item is treated as never searched.
    """
    if library_item is None:
        return 30

    last_searched: datetime | None = library_item.last_searched_at
    if last_searched is None:
        return 30

    now = datetime.utcnow()
    elapsed = now - last_searched

    if elapsed > timedelta(days=7):
        return 25
    if elapsed > timedelta(days=3):
        return 20
    if elapsed > timedelta(days=1):
        return 15
    return 5


# ---------------------------------------------------------------------------
# Reason string builder
# ---------------------------------------------------------------------------
def _build_reason(
    recency_raw: int,
    attempts_raw: int,
    staleness_raw: int,
    weighted_recency: float,
    weighted_attempts: float,
    weighted_staleness: float,
    library_item: Any | None,
) -> str:
    """Return a human-readable string describing the dominant scoring factor."""
    dominant = max(
        ("recency", weighted_recency),
        ("attempts", weighted_attempts),
        ("staleness", weighted_staleness),
        key=lambda x: x[1],
    )

    factor_name = dominant[0]

    if factor_name == "recency":
        if recency_raw >= 30:
            return "recently aired"
        if recency_raw <= 10:
            return "older content"
        return "default priority"

    if factor_name == "attempts":
        search_attempts = 0
        if library_item is not None:
            search_attempts = library_item.search_attempts or 0
        if search_attempts == 0:
            return "never searched"
        if search_attempts > 10:
            return f"searched {search_attempts}x, low results"
        return "default priority"

    if factor_name == "staleness":
        return "not searched recently"

    return "default priority"


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------
def compute_score(
    record: dict[str, Any],
    library_item: Any | None,
    strategy: str,
) -> tuple[float, str]:
    """Compute a 0-100 priority score for a wanted item.

    Args:
        record: Item dict from Sonarr/Radarr wanted API. Expected keys
            include ``airDateUtc``, ``added``, ``id``, ``title``, etc.
        library_item: A :class:`LibraryItem` model instance (has
            ``.search_attempts``, ``.last_searched_at``,
            ``.grabs_confirmed``) or ``None`` if the item hasn't been
            synced yet.
        strategy: One of ``"missing"``, ``"cutoff_unmet"``, ``"recent"``.
            Falls back to equal weights for unknown strategies.

    Returns:
        A ``(score, reason)`` tuple where *score* is a float 0-100
        (rounded to 1 decimal) and *reason* is a human-readable string
        describing the dominant factor.
    """
    weights = STRATEGY_WEIGHTS.get(strategy, DEFAULT_WEIGHTS)

    # Raw factor scores
    recency_raw = _recency_score(record)
    attempts_raw = _attempts_score(library_item)
    staleness_raw = _staleness_score(library_item)

    # Weighted contributions
    weighted_recency = recency_raw * weights["recency"]
    weighted_attempts = attempts_raw * weights["attempts"]
    weighted_staleness = staleness_raw * weights["staleness"]

    weighted_sum = weighted_recency + weighted_attempts + weighted_staleness

    # Maximum possible weighted sum (for normalization)
    max_weighted_sum = (
        MAX_RECENCY * weights["recency"]
        + MAX_ATTEMPTS * weights["attempts"]
        + MAX_STALENESS * weights["staleness"]
    )

    # Normalize to 0-100
    if max_weighted_sum == 0:
        score = 0.0
    else:
        score = min(100.0, (weighted_sum / max_weighted_sum) * 100)

    score = round(score, 1)

    reason = _build_reason(
        recency_raw,
        attempts_raw,
        staleness_raw,
        weighted_recency,
        weighted_attempts,
        weighted_staleness,
        library_item,
    )

    return (score, reason)
