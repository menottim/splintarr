"""
Integration tests for Dashboard API endpoints.

Tests the web UI dashboard endpoints including:
- Setup wizard flow
- Login page
- Dashboard pages with authentication
- Dashboard statistics API
"""

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from splintarr.core.security import hash_password
from splintarr.models.instance import Instance
from splintarr.models.search_history import SearchHistory
from splintarr.models.search_queue import SearchQueue
from splintarr.models.user import User


@pytest.fixture
def admin_user(db_session: Session) -> User:
    """Create an admin user for testing."""
    user = User(
        username="admin",
        password_hash=hash_password("SecureP@ssw0rd123!"),
        is_active=True,
        is_superuser=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def auth_cookies(client: TestClient, admin_user: User) -> dict[str, str]:
    """Get authentication cookies for testing."""
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "SecureP@ssw0rd123!"},
    )
    assert response.status_code == status.HTTP_200_OK

    # Extract cookies
    cookies = {}
    for cookie in response.cookies.jar:
        cookies[cookie.name] = cookie.value

    return cookies


class TestRootRedirect:
    """Tests for root endpoint redirects."""

    def test_root_redirects_to_setup_when_no_users(self, client: TestClient, db_session: Session):
        """Root should redirect to /setup when no users exist."""
        # Ensure no users exist
        db_session.query(User).delete()
        db_session.commit()

        response = client.get("/", follow_redirects=False)
        assert response.status_code == status.HTTP_302_FOUND
        assert response.headers["location"] == "/setup"

    def test_root_redirects_to_login_when_not_authenticated(
        self, client: TestClient, admin_user: User
    ):
        """Root should redirect to /login when not authenticated."""
        response = client.get("/", follow_redirects=False)
        assert response.status_code == status.HTTP_302_FOUND
        assert response.headers["location"] == "/login"

    def test_root_redirects_to_dashboard_when_authenticated(
        self, client: TestClient, auth_cookies: dict[str, str]
    ):
        """Root should redirect to /dashboard when authenticated."""
        response = client.get("/", cookies=auth_cookies, follow_redirects=False)
        assert response.status_code == status.HTTP_302_FOUND
        assert response.headers["location"] == "/dashboard"


class TestLoginPage:
    """Tests for login page."""

    def test_login_page_accessible(self, client: TestClient, admin_user: User):
        """Login page should be accessible."""
        response = client.get("/login")
        assert response.status_code == status.HTTP_200_OK
        assert b"Login" in response.content

    def test_login_redirects_to_dashboard_when_authenticated(
        self, client: TestClient, auth_cookies: dict[str, str]
    ):
        """Login page should redirect to dashboard when already authenticated."""
        response = client.get("/login", cookies=auth_cookies, follow_redirects=False)
        assert response.status_code == status.HTTP_302_FOUND
        assert response.headers["location"] == "/dashboard"

    def test_login_redirects_to_setup_when_no_users(self, client: TestClient, db_session: Session):
        """Login page should redirect to setup when no users exist."""
        # Ensure no users exist
        db_session.query(User).delete()
        db_session.commit()

        response = client.get("/login", follow_redirects=False)
        assert response.status_code == status.HTTP_302_FOUND
        assert response.headers["location"] == "/setup"


class TestSetupWizard:
    """Tests for setup wizard flow."""

    def test_setup_welcome_page_accessible_when_no_users(
        self, client: TestClient, db_session: Session
    ):
        """Setup wizard welcome page should be accessible when no users exist."""
        # Ensure no users exist
        db_session.query(User).delete()
        db_session.commit()

        response = client.get("/setup")
        assert response.status_code == status.HTTP_200_OK
        assert b"Welcome to Splintarr" in response.content

    def test_setup_redirects_when_users_exist(self, client: TestClient, admin_user: User):
        """Setup wizard should redirect to / when users already exist."""
        response = client.get("/setup", follow_redirects=False)
        assert response.status_code == status.HTTP_302_FOUND
        assert response.headers["location"] == "/"

    def test_setup_admin_page_accessible_when_no_users(
        self, client: TestClient, db_session: Session
    ):
        """Setup admin page should be accessible when no users exist."""
        # Ensure no users exist
        db_session.query(User).delete()
        db_session.commit()

        response = client.get("/setup/admin")
        assert response.status_code == status.HTTP_200_OK
        assert b"Create Admin Account" in response.content

    def test_setup_admin_create_success(self, client: TestClient, db_session: Session):
        """Should create admin account and redirect to instance setup."""
        # Ensure no users exist
        db_session.query(User).delete()
        db_session.commit()

        response = client.post(
            "/setup/admin",
            data={
                "username": "newadmin",
                "password": "NewSecureP@ssw0rd123!",
                "confirm_password": "NewSecureP@ssw0rd123!",
            },
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_302_FOUND
        assert response.headers["location"] == "/setup/instance"

        # Verify user was created
        user = db_session.query(User).filter(User.username == "newadmin").first()
        assert user is not None
        assert user.is_superuser is True

    def test_setup_admin_create_password_mismatch(self, client: TestClient, db_session: Session):
        """Should fail when passwords don't match."""
        # Ensure no users exist
        db_session.query(User).delete()
        db_session.commit()

        response = client.post(
            "/setup/admin",
            data={
                "username": "newadmin",
                "password": "NewSecureP@ssw0rd123!",
                "confirm_password": "DifferentP@ssw0rd123!",
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert b"Passwords do not match" in response.content

    def test_setup_instance_page_requires_auth(
        self, client: TestClient, db_session: Session, auth_cookies: dict[str, str]
    ):
        """Setup instance page should require authentication."""
        response = client.get("/setup/instance", cookies=auth_cookies)
        assert response.status_code == status.HTTP_200_OK
        assert b"Add Your First Instance" in response.content

    def test_setup_instance_page_rejects_unauthenticated(
        self, client: TestClient, db_session: Session
    ):
        """Setup instance page should reject unauthenticated requests."""
        response = client.get("/setup/instance")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_setup_complete_page_requires_auth(
        self, client: TestClient, auth_cookies: dict[str, str]
    ):
        """Setup complete page should require authentication."""
        response = client.get("/setup/complete", cookies=auth_cookies)
        assert response.status_code == status.HTTP_200_OK
        assert b"Setup Complete" in response.content


class TestDashboardPages:
    """Tests for dashboard pages."""

    def test_dashboard_index_requires_auth(self, client: TestClient, admin_user: User):
        """Dashboard index should require authentication."""
        response = client.get("/dashboard")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_dashboard_index_accessible_when_authenticated(
        self, client: TestClient, auth_cookies: dict[str, str]
    ):
        """Dashboard index should be accessible when authenticated."""
        response = client.get("/dashboard", cookies=auth_cookies)
        assert response.status_code == status.HTTP_200_OK
        assert b"Dashboard" in response.content

    def test_dashboard_instances_requires_auth(self, client: TestClient):
        """Dashboard instances page should require authentication."""
        response = client.get("/dashboard/instances")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_dashboard_instances_accessible_when_authenticated(
        self, client: TestClient, auth_cookies: dict[str, str]
    ):
        """Dashboard instances page should be accessible when authenticated."""
        response = client.get("/dashboard/instances", cookies=auth_cookies)
        assert response.status_code == status.HTTP_200_OK
        assert b"Instance Management" in response.content

    def test_dashboard_search_queues_requires_auth(self, client: TestClient):
        """Dashboard search queues page should require authentication."""
        response = client.get("/dashboard/search-queues")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_dashboard_search_queues_accessible_when_authenticated(
        self, client: TestClient, auth_cookies: dict[str, str]
    ):
        """Dashboard search queues page should be accessible when authenticated."""
        response = client.get("/dashboard/search-queues", cookies=auth_cookies)
        assert response.status_code == status.HTTP_200_OK
        assert b"Search Queue Management" in response.content

    def test_dashboard_search_history_requires_auth(self, client: TestClient):
        """Dashboard search history page should require authentication."""
        response = client.get("/dashboard/search-history")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_dashboard_search_history_accessible_when_authenticated(
        self, client: TestClient, auth_cookies: dict[str, str]
    ):
        """Dashboard search history page should be accessible when authenticated."""
        response = client.get("/dashboard/search-history", cookies=auth_cookies)
        assert response.status_code == status.HTTP_200_OK
        assert b"Search History" in response.content

    def test_dashboard_settings_requires_auth(self, client: TestClient):
        """Dashboard settings page should require authentication."""
        response = client.get("/dashboard/settings")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_dashboard_settings_accessible_when_authenticated(
        self, client: TestClient, auth_cookies: dict[str, str]
    ):
        """Dashboard settings page should be accessible when authenticated."""
        response = client.get("/dashboard/settings", cookies=auth_cookies)
        assert response.status_code == status.HTTP_200_OK
        assert b"Settings" in response.content


class TestDashboardAPI:
    """Tests for dashboard API endpoints (JSON)."""

    def test_dashboard_stats_requires_auth(self, client: TestClient):
        """Dashboard stats API should require authentication."""
        response = client.get("/api/dashboard/stats")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_dashboard_stats_returns_correct_structure(
        self, client: TestClient, auth_cookies: dict[str, str], db_session: Session, admin_user: User
    ):
        """Dashboard stats API should return correct data structure."""
        # Create test data
        instance = Instance(
            user_id=admin_user.id,
            name="Test Sonarr",
            instance_type="sonarr",
            url="http://localhost:8989",
            api_key_encrypted=b"encrypted_key",
            is_active=True,
        )
        db_session.add(instance)
        db_session.commit()

        response = client.get("/api/dashboard/stats", cookies=auth_cookies)
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert "instances" in data
        assert "search_queues" in data
        assert "searches" in data

        assert data["instances"]["total"] >= 1
        assert "active" in data["instances"]
        assert "inactive" in data["instances"]

        assert "total" in data["search_queues"]
        assert "active" in data["search_queues"]
        assert "paused" in data["search_queues"]

        assert "today" in data["searches"]
        assert "this_week" in data["searches"]
        assert "success_rate" in data["searches"]

    def test_dashboard_activity_requires_auth(self, client: TestClient):
        """Dashboard activity API should require authentication."""
        response = client.get("/api/dashboard/activity")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_dashboard_activity_returns_correct_structure(
        self, client: TestClient, auth_cookies: dict[str, str], db_session: Session, admin_user: User
    ):
        """Dashboard activity API should return correct data structure."""
        # Create test data
        instance = Instance(
            user_id=admin_user.id,
            name="Test Sonarr",
            instance_type="sonarr",
            url="http://localhost:8989",
            api_key_encrypted=b"encrypted_key",
            is_active=True,
        )
        db_session.add(instance)
        db_session.flush()

        search_history = SearchHistory(
            instance_id=instance.id,
            strategy="recent",
            status="completed",
            items_searched=10,
            items_found=3,
        )
        db_session.add(search_history)
        db_session.commit()

        response = client.get("/api/dashboard/activity", cookies=auth_cookies)
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert "activity" in data
        assert isinstance(data["activity"], list)

        if len(data["activity"]) > 0:
            activity = data["activity"][0]
            assert "id" in activity
            assert "instance_name" in activity
            assert "strategy" in activity
            assert "status" in activity
            assert "items_searched" in activity
            assert "items_found" in activity

    def test_dashboard_activity_respects_limit_parameter(
        self, client: TestClient, auth_cookies: dict[str, str]
    ):
        """Dashboard activity API should respect limit parameter."""
        response = client.get("/api/dashboard/activity?limit=5", cookies=auth_cookies)
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert len(data["activity"]) <= 5


class TestDashboardPagination:
    """Tests for paginated dashboard views."""

    def test_search_history_pagination(
        self, client: TestClient, auth_cookies: dict[str, str], db_session: Session, admin_user: User
    ):
        """Search history should support pagination."""
        # Create test instance
        instance = Instance(
            user_id=admin_user.id,
            name="Test Sonarr",
            instance_type="sonarr",
            url="http://localhost:8989",
            api_key_encrypted=b"encrypted_key",
            is_active=True,
        )
        db_session.add(instance)
        db_session.flush()

        # Create multiple search history entries
        for i in range(25):
            search_history = SearchHistory(
                instance_id=instance.id,
                strategy="recent",
                status="completed",
                items_searched=10,
                items_found=i % 5,
            )
            db_session.add(search_history)

        db_session.commit()

        # Test first page
        response = client.get("/dashboard/search-history?page=1", cookies=auth_cookies)
        assert response.status_code == status.HTTP_200_OK
        assert b"Page 1 of" in response.content

        # Test second page
        response = client.get("/dashboard/search-history?page=2", cookies=auth_cookies)
        assert response.status_code == status.HTTP_200_OK
        assert b"Page 2 of" in response.content


class TestDashboardSecurity:
    """Tests for dashboard security measures."""

    def test_dashboard_pages_reject_invalid_token(self, client: TestClient, admin_user: User):
        """Dashboard pages should reject invalid authentication tokens."""
        invalid_cookies = {"access_token": "invalid.token.here"}

        response = client.get("/dashboard", cookies=invalid_cookies)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_dashboard_api_rejects_invalid_token(self, client: TestClient, admin_user: User):
        """Dashboard API endpoints should reject invalid tokens."""
        invalid_cookies = {"access_token": "invalid.token.here"}

        response = client.get("/api/dashboard/stats", cookies=invalid_cookies)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_setup_wizard_rejects_authenticated_access_when_users_exist(
        self, client: TestClient, auth_cookies: dict[str, str]
    ):
        """Setup wizard should not be accessible when users exist."""
        response = client.get("/setup", cookies=auth_cookies, follow_redirects=False)
        assert response.status_code == status.HTTP_302_FOUND
        assert response.headers["location"] == "/"


class TestDashboardWithData:
    """Tests for dashboard with realistic data."""

    @pytest.fixture
    def populated_database(
        self, db_session: Session, admin_user: User
    ) -> tuple[Instance, SearchQueue, list[SearchHistory]]:
        """Populate database with realistic test data."""
        # Create instance
        instance = Instance(
            user_id=admin_user.id,
            name="Main Sonarr",
            instance_type="sonarr",
            url="http://localhost:8989",
            api_key_encrypted=b"encrypted_key",
            is_active=True,
        )
        db_session.add(instance)
        db_session.flush()

        # Create search queue
        queue = SearchQueue(
            instance_id=instance.id,
            name="Recent TV Shows",
            strategy="recent",
            is_recurring=True,
            interval_hours=24,
            status="pending",
            is_active=True,
        )
        db_session.add(queue)
        db_session.flush()

        # Create search history
        history_entries = []
        for i in range(5):
            entry = SearchHistory(
                instance_id=instance.id,
                search_queue_id=queue.id,
                strategy="recent",
                status="completed" if i % 2 == 0 else "failed",
                items_searched=10 + i,
                items_found=i if i % 2 == 0 else 0,
            )
            db_session.add(entry)
            history_entries.append(entry)

        db_session.commit()

        return instance, queue, history_entries

    def test_dashboard_displays_populated_data(
        self, client: TestClient, auth_cookies: dict[str, str], populated_database
    ):
        """Dashboard should correctly display populated data."""
        instance, queue, history = populated_database

        response = client.get("/dashboard", cookies=auth_cookies)
        assert response.status_code == status.HTTP_200_OK

        # Check that instance name appears
        assert instance.name.encode() in response.content

        # Check that statistics are displayed
        assert b"Instances" in response.content
        assert b"Search Queues" in response.content
        assert b"Searches Today" in response.content

    def test_dashboard_stats_with_populated_data(
        self, client: TestClient, auth_cookies: dict[str, str], populated_database
    ):
        """Dashboard stats API should calculate correct values with populated data."""
        instance, queue, history = populated_database

        response = client.get("/api/dashboard/stats", cookies=auth_cookies)
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["instances"]["total"] >= 1
        assert data["search_queues"]["total"] >= 1
        assert data["searches"]["this_week"] >= 3  # At least some completed searches
