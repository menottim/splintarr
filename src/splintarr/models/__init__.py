"""
Database models for Splintarr.

This module exports all SQLAlchemy models for easy import throughout the application.
All models use the Base declarative base from database.py.
"""

from splintarr.models.instance import Instance
from splintarr.models.search_history import SearchHistory
from splintarr.models.search_queue import SearchQueue
from splintarr.models.user import RefreshToken, User

# Export all models
__all__ = [
    "User",
    "RefreshToken",
    "Instance",
    "SearchQueue",
    "SearchHistory",
]
