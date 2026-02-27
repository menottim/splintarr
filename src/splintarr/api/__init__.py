"""
API routers for Splintarr.

This module exports all API routers for registration with FastAPI.
"""

from splintarr.api.auth import router as auth_router
from splintarr.api.instances import router as instances_router
from splintarr.api.search_history import router as search_history_router
from splintarr.api.search_queue import router as search_queue_router

__all__ = [
    "auth_router",
    "instances_router",
    "search_queue_router",
    "search_history_router",
]
