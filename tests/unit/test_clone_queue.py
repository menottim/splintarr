"""
Unit tests for the clone search queue API endpoint.

Tests:
- Clone creates a new queue with " (copy)" suffix and same settings
- Clone of nonexistent queue returns 404
- Clone of unauthorized queue returns 403
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from splintarr.api.search_queue import clone_search_queue
from splintarr.models.instance import Instance
from splintarr.models.search_queue import SearchQueue
from splintarr.models.user import User


@pytest.fixture
def mock_user():
    """Create a mock user."""
    user = MagicMock(spec=User)
    user.id = 1
    user.username = "testuser"
    user.is_active = True
    return user


@pytest.fixture
def mock_request():
    """Create a mock request that passes slowapi isinstance check."""
    request = MagicMock(spec=Request)
    request.client.host = "127.0.0.1"
    request.url.path = "/api/search-queues/5/clone"
    request.method = "POST"
    request.state = MagicMock()
    return request


@pytest.fixture
def mock_instance():
    """Create a mock instance."""
    instance = MagicMock(spec=Instance)
    instance.id = 10
    instance.user_id = 1
    return instance


@pytest.fixture
def mock_source_queue():
    """Create a mock source queue for cloning."""
    queue = MagicMock(spec=SearchQueue)
    queue.id = 5
    queue.instance_id = 10
    queue.name = "Daily Missing"
    queue.strategy = "missing"
    queue.is_recurring = True
    queue.interval_hours = 24
    queue.filters = '{"genre": "action"}'
    queue.status = "completed"
    queue.is_active = True
    return queue


class TestCloneSearchQueue:
    """Tests for clone_search_queue endpoint logic."""

    @pytest.mark.asyncio
    @patch("splintarr.api.search_queue.get_session_factory")
    @patch("splintarr.api.search_queue.get_scheduler")
    @patch("splintarr.api.search_queue.limiter")
    async def test_clone_creates_copy_with_same_settings(
        self,
        mock_limiter,
        mock_get_scheduler,
        mock_get_session_factory,
        mock_request,
        mock_user,
        mock_instance,
        mock_source_queue,
    ):
        """Clone creates a new queue with ' (copy)' suffix and identical settings."""
        mock_db = MagicMock()

        # Mock the SearchQueue query to return source queue
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            mock_source_queue,  # First call: find source queue
            mock_instance,  # Second call: verify instance ownership
        ]

        # Track what gets added to the session
        added_objects = []
        mock_db.add.side_effect = lambda obj: added_objects.append(obj)

        # After commit and refresh, set clone attributes
        def mock_refresh(obj):
            if isinstance(obj, SearchQueue):
                obj.id = 99
                obj.consecutive_failures = 0
                obj.created_at = datetime.utcnow()
                obj.next_run = None
                obj.last_run = None

        mock_db.refresh.side_effect = mock_refresh

        # Mock scheduler
        mock_scheduler = AsyncMock()
        mock_get_scheduler.return_value = mock_scheduler

        result = await clone_search_queue.__wrapped__(
            request=mock_request,
            queue_id=5,
            db=mock_db,
            current_user=mock_user,
        )

        # Verify the response
        assert result.name == "Daily Missing (copy)"
        assert result.instance_id == 10
        assert result.strategy == "missing"
        assert result.recurring is True
        assert result.interval_hours == 24
        assert result.status == "pending"
        assert result.is_active is True
        assert result.consecutive_failures == 0
        assert result.id == 99

        # Verify a new SearchQueue was created and added
        assert len(added_objects) == 1
        clone = added_objects[0]
        assert isinstance(clone, SearchQueue)
        assert clone.name == "Daily Missing (copy)"
        assert clone.instance_id == 10
        assert clone.strategy == "missing"
        assert clone.is_recurring is True
        assert clone.interval_hours == 24
        assert clone.filters == '{"genre": "action"}'
        assert clone.status == "pending"
        assert clone.is_active is True

        # Verify DB operations
        mock_db.commit.assert_called_once()
        mock_db.refresh.assert_called_once()

        # Verify scheduler was called
        mock_scheduler.schedule_queue.assert_awaited_once_with(99)

    @pytest.mark.asyncio
    @patch("splintarr.api.search_queue.limiter")
    async def test_clone_nonexistent_queue_returns_404(
        self,
        mock_limiter,
        mock_request,
        mock_user,
    ):
        """Cloning a queue that does not exist returns 404."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await clone_search_queue.__wrapped__(
                request=mock_request,
                queue_id=99999,
                db=mock_db,
                current_user=mock_user,
            )

        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail

    @pytest.mark.asyncio
    @patch("splintarr.api.search_queue.limiter")
    async def test_clone_unauthorized_queue_returns_403(
        self,
        mock_limiter,
        mock_request,
        mock_user,
        mock_source_queue,
    ):
        """Cloning a queue owned by another user returns 403."""
        mock_db = MagicMock()

        # Source queue found, but instance ownership check fails
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            mock_source_queue,  # Found the source queue
            None,  # Instance ownership check fails (not owned by user)
        ]

        with pytest.raises(HTTPException) as exc_info:
            await clone_search_queue.__wrapped__(
                request=mock_request,
                queue_id=5,
                db=mock_db,
                current_user=mock_user,
            )

        assert exc_info.value.status_code == 403
        assert "Access denied" in exc_info.value.detail
