"""
Pydantic schemas for Search Queue and History management.

This module defines request and response models for search operations:
- Search queue creation and management
- Search history tracking
- Search strategy configuration
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Search strategies
SearchStrategy = Literal["missing", "cutoff_unmet", "recent", "custom"]

# Includes "custom" for backwards compatibility with existing DB records
SearchStrategyRead = Literal["missing", "cutoff_unmet", "recent", "custom"]

# Search execution status
SearchExecutionStatus = Literal["success", "partial_success", "failed"]

# Search queue status
SearchQueueStatus = Literal["pending", "in_progress", "completed", "failed", "cancelled"]


def _validate_search_name(v: str) -> str:
    """Strip and validate a search queue name (min 3 non-whitespace chars)."""
    stripped = v.strip()
    if not stripped:
        raise ValueError("Search name cannot be empty or only whitespace")
    if len(stripped) < 3:
        raise ValueError("Search name must be at least 3 characters long")
    return stripped


VALID_SCHEDULE_DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


def _validate_schedule_time(v: str) -> None:
    """Validate HH:MM is within valid range (00:00-23:59)."""
    try:
        parts = v.split(":")
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except (ValueError, IndexError) as err:
        raise ValueError(f"schedule_time must be a valid time (00:00-23:59), got '{v}'") from err


def _validate_schedule_days(v: str) -> None:
    """Validate comma-separated day tokens (mon,tue,wed,thu,fri,sat,sun)."""
    tokens = [t.strip() for t in v.split(",")]
    invalid = [t for t in tokens if t not in VALID_SCHEDULE_DAYS]
    if invalid:
        raise ValueError(
            f"Invalid schedule_days: {invalid}. "
            f"Valid values: {', '.join(sorted(VALID_SCHEDULE_DAYS))}"
        )
    if not tokens:
        raise ValueError("schedule_days must contain at least one day")


class CustomFilterConfig(BaseModel):
    """Configuration for custom strategy filters."""

    sources: list[Literal["missing", "cutoff_unmet"]] = Field(
        ..., min_length=1, description="Data sources to fetch from"
    )
    year_min: int | None = Field(None, ge=1900, le=2100)
    year_max: int | None = Field(None, ge=1900, le=2100)
    quality_profiles: list[str] = Field(default_factory=list)
    statuses: list[Literal["continuing", "ended", "upcoming", "deleted"]] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def validate_year_range(self) -> "CustomFilterConfig":
        """Validate that year_min is not greater than year_max."""
        if self.year_min and self.year_max and self.year_min > self.year_max:
            raise ValueError("year_min must be <= year_max")
        return self


class SearchQueueCreate(BaseModel):
    """
    Schema for creating a search queue item.

    Used for scheduling automated searches on Sonarr/Radarr instances.
    """

    instance_id: int = Field(
        ...,
        gt=0,
        description="ID of the instance to search on",
    )
    name: str = Field(
        ...,
        min_length=3,
        max_length=100,
        description="User-friendly name for this search (3-100 characters)",
    )
    strategy: SearchStrategy = Field(
        ...,
        description="Search strategy to use (missing, cutoff_unmet, or recent)",
    )
    recurring: bool = Field(
        default=False,
        description="Whether this search should repeat automatically",
    )
    interval_hours: int | None = Field(
        default=None,
        ge=1,
        le=168,
        description="Interval between searches in hours (1-168, required if recurring)",
    )
    schedule_mode: Literal["interval", "daily", "weekly"] = Field(
        default="interval",
        description="Schedule mode: interval, daily, or weekly",
    )
    schedule_time: str | None = Field(
        default=None,
        pattern=r"^\d{2}:\d{2}$",
        description="Time of day for daily/weekly modes (HH:MM)",
    )
    schedule_days: str | None = Field(
        default=None,
        description="Comma-separated days for weekly mode (mon,tue,wed,thu,fri,sat,sun)",
    )
    jitter_minutes: int = Field(
        default=0,
        ge=0,
        le=15,
        description="Random jitter in minutes to prevent thundering herd (0-15)",
    )
    filters: CustomFilterConfig | None = Field(
        default=None,
        description="Filter configuration for custom search strategy",
    )
    cooldown_mode: Literal["adaptive", "flat"] = Field(
        default="adaptive",
        description="Cooldown mode: 'adaptive' (tiered by age) or 'flat' (fixed hours)",
    )
    cooldown_hours: int | None = Field(
        default=None,
        ge=1,
        le=336,
        description="Fixed cooldown hours when cooldown_mode='flat' (1-336, i.e. 14 days max)",
    )
    max_items_per_run: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Maximum items to search per queue execution (1-500)",
    )
    season_pack_enabled: bool = Field(
        default=False,
        description="Enable season pack search for Sonarr instances",
    )
    season_pack_threshold: int = Field(
        default=3,
        ge=2,
        le=50,
        description="Minimum missing episodes per season to trigger season pack search (2-50)",
    )
    budget_aware: bool = Field(
        default=True,
        description="Automatically reduce batch size when indexer budget is low",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate search queue name format."""
        return _validate_search_name(v)

    @field_validator("cooldown_hours")
    @classmethod
    def validate_cooldown_hours(cls, v: int | None, info) -> int | None:
        """Validate cooldown_hours is provided when cooldown_mode is 'flat'."""
        if hasattr(info, "data") and info.data.get("cooldown_mode") == "flat":
            if v is None:
                raise ValueError("cooldown_hours is required when cooldown_mode is 'flat'")
        return v

    @model_validator(mode="after")
    def validate_custom_strategy_filters(self) -> "SearchQueueCreate":
        """Validate that custom strategy has filters and non-custom strategies do not."""
        if self.strategy == "custom" and self.filters is None:
            raise ValueError("Custom strategy requires filters")
        if self.strategy != "custom" and self.filters is not None:
            raise ValueError("Filters only allowed with custom strategy")
        return self

    @model_validator(mode="after")
    def validate_schedule_fields(self) -> "SearchQueueCreate":
        """Validate schedule fields based on schedule_mode."""
        if not self.recurring:
            return self
        if self.schedule_mode == "interval":
            if not self.interval_hours:
                raise ValueError(
                    "interval_hours is required for interval mode. "
                    "Specify how often the search should run (1-168 hours)."
                )
        elif self.schedule_mode == "daily":
            if not self.schedule_time:
                raise ValueError("schedule_time (HH:MM) is required for daily mode")
            _validate_schedule_time(self.schedule_time)
        elif self.schedule_mode == "weekly":
            if not self.schedule_time:
                raise ValueError("schedule_time (HH:MM) is required for weekly mode")
            _validate_schedule_time(self.schedule_time)
            if not self.schedule_days:
                raise ValueError("schedule_days is required for weekly mode")
            _validate_schedule_days(self.schedule_days)
        return self

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "instance_id": 1,
                    "name": "Daily Missing Episodes",
                    "strategy": "missing",
                    "recurring": True,
                    "interval_hours": 24,
                    "filters": None,
                },
                {
                    "instance_id": 2,
                    "name": "Weekly Cutoff Unmet",
                    "strategy": "cutoff_unmet",
                    "recurring": True,
                    "interval_hours": 168,
                    "filters": None,
                },
            ]
        }
    }


class SearchQueueUpdate(BaseModel):
    """
    Schema for updating an existing search queue item.

    All fields are optional. Only provided fields will be updated.
    """

    name: str | None = Field(
        default=None,
        min_length=3,
        max_length=100,
        description="User-friendly name for this search",
    )
    strategy: SearchStrategy | None = Field(
        default=None,
        description="Search strategy to use",
    )
    recurring: bool | None = Field(
        default=None,
        description="Whether this search should repeat automatically",
    )
    interval_hours: int | None = Field(
        default=None,
        ge=1,
        le=168,
        description="Interval between searches in hours (1-168)",
    )
    schedule_mode: Literal["interval", "daily", "weekly"] | None = Field(
        default=None,
        description="Schedule mode: interval, daily, or weekly",
    )
    schedule_time: str | None = Field(
        default=None,
        pattern=r"^\d{2}:\d{2}$",
        description="Time of day for daily/weekly modes (HH:MM)",
    )
    schedule_days: str | None = Field(
        default=None,
        description="Comma-separated days for weekly mode",
    )
    jitter_minutes: int | None = Field(
        default=None,
        ge=0,
        le=15,
        description="Random jitter in minutes (0-15)",
    )
    is_active: bool | None = Field(
        default=None,
        description="Whether this search is active (inactive searches won't run)",
    )
    filters: CustomFilterConfig | None = Field(
        default=None,
        description="Filter configuration for custom search strategy",
    )
    cooldown_mode: Literal["adaptive", "flat"] | None = Field(
        default=None,
        description="Cooldown mode: 'adaptive' or 'flat'",
    )
    cooldown_hours: int | None = Field(
        default=None,
        ge=1,
        le=336,
        description="Fixed cooldown hours when cooldown_mode='flat'",
    )
    max_items_per_run: int | None = Field(
        default=None,
        ge=1,
        le=500,
        description="Maximum items to search per queue execution",
    )
    season_pack_enabled: bool | None = Field(
        default=None,
        description="Enable season pack search for Sonarr instances",
    )
    season_pack_threshold: int | None = Field(
        default=None,
        ge=2,
        le=50,
        description="Minimum missing episodes per season to trigger season pack search (2-50)",
    )
    budget_aware: bool | None = Field(
        default=None,
        description="Automatically reduce batch size when indexer budget is low",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        """Validate search queue name format if provided."""
        return _validate_search_name(v) if v is not None else None

    @model_validator(mode="after")
    def validate_custom_strategy_filters(self) -> "SearchQueueUpdate":
        """Validate custom strategy / filters consistency when both are provided.

        For partial updates, only enforce the constraint when both strategy and
        filters are explicitly set. When only one is provided, the API layer
        will validate against the existing DB record.
        """
        if self.strategy is not None and self.filters is not None:
            if self.strategy != "custom":
                raise ValueError("Filters only allowed with custom strategy")
        return self

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "Updated Search Name",
                    "interval_hours": 48,
                    "is_active": True,
                }
            ]
        }
    }


class SearchQueueResponse(BaseModel):
    """
    Schema for search queue item response.

    Returned when fetching search queue details.
    """

    id: int = Field(..., description="Search queue item ID")
    instance_id: int = Field(..., description="Instance ID this search runs on")
    name: str = Field(..., description="User-friendly name")
    strategy: SearchStrategyRead = Field(..., description="Search strategy")
    recurring: bool = Field(..., description="Whether search repeats automatically")
    interval_hours: int | None = Field(
        None, description="Interval between recurring searches (hours)"
    )
    schedule_mode: str = Field(default="interval", description="Schedule mode")
    schedule_time: str | None = Field(default=None, description="Time for daily/weekly (HH:MM)")
    schedule_days: str | None = Field(default=None, description="Days for weekly mode")
    jitter_minutes: int = Field(default=0, description="Jitter minutes")
    is_active: bool = Field(..., description="Whether search is active")
    status: SearchQueueStatus = Field(..., description="Current execution status")
    next_run: datetime | None = Field(None, description="Next scheduled execution time (ISO 8601)")
    last_run: datetime | None = Field(None, description="Last execution time (ISO 8601)")
    consecutive_failures: int = Field(..., description="Number of consecutive failed executions")
    cooldown_mode: str = Field(default="adaptive", description="Cooldown mode")
    cooldown_hours: int | None = Field(default=None, description="Fixed cooldown hours")
    max_items_per_run: int = Field(default=50, description="Max items per search run")
    season_pack_enabled: bool = Field(default=False, description="Season pack search enabled")
    season_pack_threshold: int = Field(
        default=3, description="Min missing episodes per season for season pack search"
    )
    budget_aware: bool = Field(default=True, description="Budget-aware batch sizing enabled")
    created_at: datetime = Field(..., description="Queue item creation timestamp (ISO 8601)")

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "instance_id": 1,
                    "name": "Daily Missing Episodes",
                    "strategy": "missing",
                    "recurring": True,
                    "interval_hours": 24,
                    "is_active": True,
                    "status": "pending",
                    "next_run": "2024-01-16T10:00:00Z",
                    "last_run": "2024-01-15T10:00:00Z",
                    "consecutive_failures": 0,
                    "created_at": "2024-01-15T10:30:00Z",
                }
            ]
        },
    }


class SearchHistoryResponse(BaseModel):
    """
    Schema for search history record response.

    Returned when fetching search execution history.
    """

    id: int = Field(..., description="History record ID")
    instance_id: int = Field(..., description="Instance ID where search was executed")
    search_queue_id: int | None = Field(
        None, description="Search queue item ID (NULL for manual searches)"
    )
    search_name: str = Field(..., description="Name of the search that was executed")
    strategy: SearchStrategyRead = Field(..., description="Search strategy that was used")
    started_at: datetime = Field(..., description="Search start timestamp (ISO 8601)")
    completed_at: datetime | None = Field(
        None, description="Search completion timestamp (ISO 8601, NULL if running)"
    )
    duration_seconds: int | None = Field(None, description="Total execution time in seconds")
    status: SearchExecutionStatus = Field(..., description="Execution status")
    items_searched: int = Field(..., description="Number of items searched")
    items_found: int = Field(..., description="Number of items matching criteria")
    searches_triggered: int = Field(..., description="Number of searches triggered")
    error_message: str | None = Field(None, description="Error message if search failed")

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "instance_id": 1,
                    "search_queue_id": 1,
                    "search_name": "Daily Missing Episodes",
                    "strategy": "missing",
                    "started_at": "2024-01-15T10:00:00Z",
                    "completed_at": "2024-01-15T10:05:23Z",
                    "duration_seconds": 323,
                    "status": "success",
                    "items_searched": 150,
                    "items_found": 23,
                    "searches_triggered": 23,
                    "error_message": None,
                }
            ]
        },
    }
