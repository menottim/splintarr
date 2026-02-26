"""
External service integrations for Vibe-Quality-Searcharr.

This package provides API clients for:
- Sonarr (TV series management)
- Radarr (Movie management)
- Search scheduling and queue management
- Search history tracking
"""

from vibe_quality_searcharr.services.radarr import RadarrClient
from vibe_quality_searcharr.services.scheduler import (
    SearchScheduler,
    get_scheduler,
    start_scheduler,
    stop_scheduler,
)
from vibe_quality_searcharr.services.search_history import SearchHistoryService, get_history_service
from vibe_quality_searcharr.services.search_queue import SearchQueueManager
from vibe_quality_searcharr.services.sonarr import SonarrClient

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
