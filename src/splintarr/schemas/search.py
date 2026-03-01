"""
Pydantic schemas for Search Queue and History management.

This module defines request and response models for search operations:
- Search queue creation and management
- Search history tracking
- Search strategy configuration
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# Search strategies
SearchStrategy = Literal["missing", "cutoff_unmet", "recent"]

# Includes "custom" for backwards compatibility with existing DB records
SearchStrategyRead = Literal["missing", "cutoff_unmet", "recent", "custom"]

# Search execution status
SearchExecutionStatus = Literal["success", "partial_success", "failed"]

# Search queue status
SearchQueueStatus = Literal["pending", "in_progress", "completed", "failed", "cancelled"]


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
    filters: dict[str, Any] | None = Field(
        default=None,
        description="JSON filters for custom search strategy",
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

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """
        Validate search queue name format.

        Args:
            v: Search name to validate

        Returns:
            str: Validated name

        Raises:
            ValueError: If name format is invalid
        """
        stripped = v.strip()
        if not stripped:
            raise ValueError("Search name cannot be empty or only whitespace")

        if len(stripped) < 3:
            raise ValueError("Search name must be at least 3 characters long")

        return stripped

    @field_validator("cooldown_hours")
    @classmethod
    def validate_cooldown_hours(cls, v: int | None, info) -> int | None:
        """Validate cooldown_hours is provided when cooldown_mode is 'flat'."""
        if hasattr(info, "data") and info.data.get("cooldown_mode") == "flat":
            if v is None:
                raise ValueError("cooldown_hours is required when cooldown_mode is 'flat'")
        return v

    @field_validator("interval_hours")
    @classmethod
    def validate_interval_hours(cls, v: int | None, info) -> int | None:
        """
        Validate interval_hours is provided if recurring is True.

        Args:
            v: Interval hours value
            info: Validation context with other field values

        Returns:
            int | None: Validated interval hours

        Raises:
            ValueError: If recurring is True but interval_hours is not provided
        """
        # Check if recurring is True
        if hasattr(info, "data") and info.data.get("recurring", False):
            if v is None:
                raise ValueError(
                    "interval_hours is required when recurring is True. "
                    "Specify how often the search should run (1-168 hours)."
                )
            if v < 1 or v > 168:
                raise ValueError("interval_hours must be between 1 and 168 hours (7 days)")
        elif v is not None:
            # If recurring is False but interval_hours is provided, that's OK but warn
            pass

        return v

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
    is_active: bool | None = Field(
        default=None,
        description="Whether this search is active (inactive searches won't run)",
    )
    filters: dict[str, Any] | None = Field(
        default=None,
        description="JSON filters for custom search strategy",
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

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        """Validate search queue name format if provided."""
        if v is None:
            return v

        stripped = v.strip()
        if not stripped:
            raise ValueError("Search name cannot be empty or only whitespace")

        if len(stripped) < 3:
            raise ValueError("Search name must be at least 3 characters long")

        return stripped

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
    is_active: bool = Field(..., description="Whether search is active")
    status: SearchQueueStatus = Field(..., description="Current execution status")
    next_run: datetime | None = Field(None, description="Next scheduled execution time (ISO 8601)")
    last_run: datetime | None = Field(None, description="Last execution time (ISO 8601)")
    consecutive_failures: int = Field(..., description="Number of consecutive failed executions")
    cooldown_mode: str = Field(default="adaptive", description="Cooldown mode")
    cooldown_hours: int | None = Field(default=None, description="Fixed cooldown hours")
    max_items_per_run: int = Field(default=50, description="Max items per search run")
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
