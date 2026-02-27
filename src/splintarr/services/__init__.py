"""
External service integrations for Splintarr.

This package provides API clients for:
- Sonarr (TV series management)
- Radarr (Movie management)
- Search scheduling and queue management
- Search history tracking
"""

from splintarr.services.radarr import RadarrClient
from splintarr.services.scheduler import (
    SearchScheduler,
    get_scheduler,
    start_scheduler,
    stop_scheduler,
)
from splintarr.services.search_history import SearchHistoryService, get_history_service
from splintarr.services.search_queue import SearchQueueManager
from splintarr.services.sonarr import SonarrClient

__all__ = [
    "SonarrClient",
    "RadarrClient",
    "SearchScheduler",
    "get_scheduler",
    "start_scheduler",
    "stop_scheduler",
    "SearchQueueManager",
    "SearchHistoryService",
    "get_history_service",
]
