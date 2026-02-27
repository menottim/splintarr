"""
Integration tests for Search Queue API endpoints.

Tests API functionality including authentication, authorization, and business logic.
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from fastapi import status
from fastapi.testclient import TestClient

from splintarr.main import app
from splintarr.models import Instance, SearchQueue, User
from splintarr.core.auth import create_access_token


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def test_user(db_session):
    """Create test user."""
    from splintarr.core.security import hash_password

    user = User(
        username="testuser",
        email="test@example.com",
        password_hash=hash_password("testpassword"),
        is_active=True,
        totp_enabled=False,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def test_instance(db_session, test_user):
    """Create test instance."""
    from splintarr.core.security import encrypt_field

    instance = Instance(
        user_id=test_user.id,
        name="Test Sonarr",
        type="sonarr",
        url="https://sonarr.example.com",
        encrypted_api_key=encrypt_field("test_api_key_1234567890"),
        verify_ssl=True,
        rate_limit=5.0,
    )
    db_session.add(instance)
    db_session.commit()
    db_session.refresh(instance)
    return instance


@pytest.fixture
def auth_headers(test_user):
    """Create authentication headers."""
    token = create_access_token({"sub": test_user.username})
    return {"Authorization": f"Bearer {token}"}


class TestCreateSearchQueue:
    """Test creating search queues."""

    def test_create_search_queue_success(
        self, client, db_session, test_user, test_instance, auth_headers
    ):
        """Test successful search queue creation."""
        data = {
            "instance_id": test_instance.id,
            "name": "Daily Missing Episodes",
            "strategy": "missing",
            "recurring": True,
            "interval_hours": 24,
        }

        response = client.post(
            "/api/search-queues",
            json=data,
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_201_CREATED
        result = response.json()

        assert result["name"] == data["name"]
        assert result["strategy"] == data["strategy"]
        assert result["recurring"] == data["recurring"]
        assert result["interval_hours"] == data["interval_hours"]
        assert result["is_active"] is True
        assert result["status"] == "pending"

    def test_create_search_queue_requires_auth(self, client, test_instance):
        """Test that creating queue requires authentication."""
        data = {
            "instance_id": test_instance.id,
            "name": "Test Queue",
            "strategy": "missing",
            "recurring": False,
        }

        response = client.post("/api/search-queues", json=data)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_create_search_queue_invalid_instance(
        self, client, test_user, auth_headers
    ):
        """Test creating queue with non-existent instance."""
        data = {
            "instance_id": 999,
            "name": "Test Queue",
            "strategy": "missing",
            "recurring": False,
        }

        response = client.post(
            "/api/search-queues",
            json=data,
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_create_search_queue_validation(self, client, test_instance, auth_headers):
        """Test input validation."""
        # Missing required field
        data = {
            "instance_id": test_instance.id,
            "strategy": "missing",
        }

        response = client.post(
            "/api/search-queues",
            json=data,
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_create_recurring_queue_requires_interval(
        self, client, test_instance, auth_headers
    ):
        """Test that recurring queues require interval_hours."""
        data = {
            "instance_id": test_instance.id,
            "name": "Test Queue",
            "strategy": "missing",
            "recurring": True,
            # Missing interval_hours
        }

        response = client.post(
            "/api/search-queues",
            json=data,
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestListSearchQueues:
    """Test listing search queues."""

    def test_list_search_queues_empty(self, client, test_user, auth_headers):
        """Test listing when no queues exist."""
        response = client.get("/api/search-queues", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        result = response.json()
        assert isinstance(result, list)
        assert len(result) == 0

    def test_list_search_queues_with_data(
        self, client, db_session, test_instance, auth_headers
    ):
        """Test listing queues with data."""
        # Create test queues
        for i in range(3):
            queue = SearchQueue(
                instance_id=test_instance.id,
                name=f"Test Queue {i}",
                strategy="missing",
                is_recurring=True,
                interval_hours=24,
                is_active=True,
                status="pending",
            )
            db_session.add(queue)

        db_session.commit()

        response = client.get("/api/search-queues", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        result = response.json()
        assert len(result) == 3

    def test_list_search_queues_requires_auth(self, client):
        """Test that listing requires authentication."""
        response = client.get("/api/search-queues")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestGetSearchQueue:
    """Test getting individual search queue."""

    def test_get_search_queue_success(
        self, client, db_session, test_instance, auth_headers
    ):
        """Test getting a queue by ID."""
        # Create queue
        queue = SearchQueue(
            instance_id=test_instance.id,
            name="Test Queue",
            strategy="missing",
            is_recurring=False,
            is_active=True,
            status="pending",
        )
        db_session.add(queue)
        db_session.commit()
        db_session.refresh(queue)

        response = client.get(
            f"/api/search-queues/{queue.id}",
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        result = response.json()
        assert result["id"] == queue.id
        assert result["name"] == queue.name

    def test_get_search_queue_not_found(self, client, auth_headers):
        """Test getting non-existent queue."""
        response = client.get("/api/search-queues/999", headers=auth_headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestUpdateSearchQueue:
    """Test updating search queues."""

    def test_update_search_queue_success(
        self, client, db_session, test_instance, auth_headers
    ):
        """Test updating a queue."""
        # Create queue
        queue = SearchQueue(
            instance_id=test_instance.id,
            name="Original Name",
            strategy="missing",
            is_recurring=True,
            interval_hours=24,
            is_active=True,
            status="pending",
        )
        db_session.add(queue)
        db_session.commit()
        db_session.refresh(queue)

        # Update
        update_data = {
            "name": "Updated Name",
            "interval_hours": 48,
        }

        response = client.put(
            f"/api/search-queues/{queue.id}",
            json=update_data,
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        result = response.json()
        assert result["name"] == "Updated Name"
        assert result["interval_hours"] == 48

    def test_update_search_queue_deactivate(
        self, client, db_session, test_instance, auth_headers
    ):
        """Test deactivating a queue."""
        # Create queue
        queue = SearchQueue(
            instance_id=test_instance.id,
            name="Test Queue",
            strategy="missing",
            is_recurring=True,
            interval_hours=24,
            is_active=True,
            status="pending",
        )
        db_session.add(queue)
        db_session.commit()
        db_session.refresh(queue)

        # Deactivate
        update_data = {"is_active": False}

        response = client.put(
            f"/api/search-queues/{queue.id}",
            json=update_data,
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        result = response.json()
        assert result["is_active"] is False


class TestDeleteSearchQueue:
    """Test deleting search queues."""

    def test_delete_search_queue_success(
        self, client, db_session, test_instance, auth_headers
    ):
        """Test deleting a queue."""
        # Create queue
        queue = SearchQueue(
            instance_id=test_instance.id,
            name="Test Queue",
            strategy="missing",
            is_recurring=False,
            is_active=True,
            status="pending",
        )
        db_session.add(queue)
        db_session.commit()
        queue_id = queue.id

        response = client.delete(
            f"/api/search-queues/{queue_id}",
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify queue is deleted
        deleted_queue = db_session.query(SearchQueue).filter_by(id=queue_id).first()
        assert deleted_queue is None

    def test_delete_search_queue_not_found(self, client, auth_headers):
        """Test deleting non-existent queue."""
        response = client.delete("/api/search-queues/999", headers=auth_headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestQueueControl:
    """Test queue control operations (start, pause, resume)."""

    @patch("splintarr.api.search_queue.SearchQueueManager")
    def test_start_search_queue(
        self, mock_manager, client, db_session, test_instance, auth_headers
    ):
        """Test manually starting a queue."""
        # Create queue
        queue = SearchQueue(
            instance_id=test_instance.id,
            name="Test Queue",
            strategy="missing",
            is_recurring=False,
            is_active=True,
            status="pending",
        )
        db_session.add(queue)
        db_session.commit()
        db_session.refresh(queue)

        # Mock manager
        mock_instance = AsyncMock()
        mock_instance.execute_queue.return_value = {
            "status": "success",
            "items_searched": 10,
            "items_found": 5,
            "searches_triggered": 5,
        }
        mock_manager.return_value = mock_instance

        response = client.post(
            f"/api/search-queues/{queue.id}/start",
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        result = response.json()
        assert "message" in result

    def test_pause_search_queue(
        self, client, db_session, test_instance, auth_headers
    ):
        """Test pausing a queue."""
        # Create active queue
        queue = SearchQueue(
            instance_id=test_instance.id,
            name="Test Queue",
            strategy="missing",
            is_recurring=True,
            interval_hours=24,
            is_active=True,
            status="pending",
        )
        db_session.add(queue)
        db_session.commit()
        db_session.refresh(queue)

        response = client.post(
            f"/api/search-queues/{queue.id}/pause",
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify queue is paused
        db_session.refresh(queue)
        assert queue.is_active is False

    def test_resume_search_queue(
        self, client, db_session, test_instance, auth_headers
    ):
        """Test resuming a paused queue."""
        # Create paused queue
        queue = SearchQueue(
            instance_id=test_instance.id,
            name="Test Queue",
            strategy="missing",
            is_recurring=True,
            interval_hours=24,
            is_active=False,
            status="pending",
        )
        db_session.add(queue)
        db_session.commit()
        db_session.refresh(queue)

        response = client.post(
            f"/api/search-queues/{queue.id}/resume",
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify queue is active
        db_session.refresh(queue)
        assert queue.is_active is True


class TestQueueStatus:
    """Test queue status endpoint."""

    @patch("splintarr.api.search_queue.get_history_service")
    def test_get_queue_status(
        self, mock_service, client, db_session, test_instance, auth_headers
    ):
        """Test getting queue status and performance."""
        # Create queue
        queue = SearchQueue(
            instance_id=test_instance.id,
            name="Test Queue",
            strategy="missing",
            is_recurring=True,
            interval_hours=24,
            is_active=True,
            status="pending",
        )
        db_session.add(queue)
        db_session.commit()
        db_session.refresh(queue)

        # Mock history service
        mock_instance = mock_service.return_value
        mock_instance.get_queue_performance.return_value = {
            "total_executions": 10,
            "success_rate": 0.8,
            "avg_items_found": 25.5,
            "avg_duration": 300.0,
            "last_success": datetime.utcnow(),
            "last_failure": None,
        }

        response = client.get(
            f"/api/search-queues/{queue.id}/status",
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        result = response.json()

        assert result["queue_id"] == queue.id
        assert result["name"] == queue.name
        assert "performance" in result
