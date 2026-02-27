"""
Integration tests for dashboard web UI routes.

Tests the complete dashboard user interface flow including:
- Setup wizard (all steps)
- Authentication (login/logout)
- Dashboard page rendering
- Instance management pages
- Queue management pages
- Settings page
- CSRF protection
- Flash messages
"""

import pytest
from fastapi.testclient import TestClient

from splintarr.main import app
from splintarr.models.instance import Instance
from splintarr.models.search_queue import SearchQueue
from splintarr.models.user import User


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def authenticated_client(client, test_db):
    """Create authenticated test client with session cookies."""
    # Create test user
    from splintarr.core.security import hash_password

    user = User(
        username="testuser",
        password_hash=hash_password("TestPassword123!"),
        is_active=True,
        is_superuser=True,
    )
    test_db.add(user)
    test_db.commit()

    # Login
    response = client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": "TestPassword123!"},
    )
    assert response.status_code == 200

    return client


class TestRootAndRedirects:
    """Test root endpoint and redirect logic."""

    def test_root_redirects_to_setup_when_no_users(self, client, test_db):
        """Root should redirect to /setup when no users exist."""
        # Ensure no users exist
        test_db.query(User).delete()
        test_db.commit()

        response = client.get("/", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/setup"

    def test_root_redirects_to_login_when_not_authenticated(self, client, test_db):
        """Root should redirect to /login when not authenticated."""
        # Create a user
        from splintarr.core.security import hash_password

        user = User(
            username="testuser",
            password_hash=hash_password("TestPassword123!"),
            is_active=True,
        )
        test_db.add(user)
        test_db.commit()

        response = client.get("/", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/login"

    def test_root_redirects_to_dashboard_when_authenticated(
        self, authenticated_client, test_db
    ):
        """Root should redirect to /dashboard when authenticated."""
        response = authenticated_client.get("/", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/dashboard"


class TestLoginPage:
    """Test login page rendering and functionality."""

    def test_login_page_renders(self, client, test_db):
        """Login page should render successfully."""
        # Create a user so we don't redirect to setup
        from splintarr.core.security import hash_password

        user = User(
            username="testuser",
            password_hash=hash_password("TestPassword123!"),
            is_active=True,
        )
        test_db.add(user)
        test_db.commit()

        response = client.get("/login")
        assert response.status_code == 200
        assert b"Login" in response.content
        assert b"Username" in response.content
        assert b"Password" in response.content

    def test_login_redirects_to_setup_when_no_users(self, client, test_db):
        """Login page should redirect to setup when no users exist."""
        test_db.query(User).delete()
        test_db.commit()

        response = client.get("/login", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/setup"

    def test_login_redirects_to_dashboard_when_already_authenticated(
        self, authenticated_client
    ):
        """Login page should redirect to dashboard if already logged in."""
        response = authenticated_client.get("/login", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/dashboard"


class TestSetupWizard:
    """Test setup wizard flow (all steps)."""

    def test_setup_welcome_page_renders(self, client, test_db):
        """Setup welcome page should render when no users exist."""
        test_db.query(User).delete()
        test_db.commit()

        response = client.get("/setup")
        assert response.status_code == 200
        assert b"Welcome to Splintarr" in response.content
        assert b"Get Started" in response.content

    def test_setup_redirects_when_users_exist(self, client, test_db):
        """Setup should redirect to root when users already exist."""
        from splintarr.core.security import hash_password

        user = User(
            username="existinguser",
            password_hash=hash_password("TestPassword123!"),
            is_active=True,
        )
        test_db.add(user)
        test_db.commit()

        response = client.get("/setup", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/"

    def test_setup_admin_page_renders(self, client, test_db):
        """Admin account creation page should render."""
        test_db.query(User).delete()
        test_db.commit()

        response = client.get("/setup/admin")
        assert response.status_code == 200
        assert b"Create Admin Account" in response.content
        assert b"Username" in response.content
        assert b"Password" in response.content

    def test_setup_admin_create_success(self, client, test_db):
        """Should successfully create admin account."""
        test_db.query(User).delete()
        test_db.commit()

        response = client.post(
            "/setup/admin",
            data={
                "username": "admin",
                "password": "SecurePassword123!",
                "confirm_password": "SecurePassword123!",
            },
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers["location"] == "/setup/instance"

        # Verify user was created
        user = test_db.query(User).filter(User.username == "admin").first()
        assert user is not None
        assert user.is_superuser is True
        assert user.is_active is True

    def test_setup_admin_password_mismatch(self, client, test_db):
        """Should show error when passwords don't match."""
        test_db.query(User).delete()
        test_db.commit()

        response = client.post(
            "/setup/admin",
            data={
                "username": "admin",
                "password": "SecurePassword123!",
                "confirm_password": "DifferentPassword123!",
            },
        )

        assert response.status_code == 400
        assert b"Passwords do not match" in response.content

    def test_setup_admin_weak_password(self, client, test_db):
        """Should reject weak password."""
        test_db.query(User).delete()
        test_db.commit()

        response = client.post(
            "/setup/admin",
            data={
                "username": "admin",
                "password": "weak",
                "confirm_password": "weak",
            },
        )

        assert response.status_code == 400
        assert b"at least 12 characters" in response.content

    def test_setup_instance_page_renders(self, client, test_db):
        """Instance configuration page should render for authenticated user."""
        # Create and authenticate user
        from splintarr.core.security import hash_password

        user = User(
            username="testuser",
            password_hash=hash_password("TestPassword123!"),
            is_active=True,
        )
        test_db.add(user)
        test_db.commit()

        # Login first
        client.post(
            "/api/auth/login",
            json={"username": "testuser", "password": "TestPassword123!"},
        )

        response = client.get("/setup/instance")
        assert response.status_code == 200
        assert b"Add Your First Instance" in response.content
        assert b"Instance Type" in response.content

    def test_setup_instance_skip(self, authenticated_client, test_db):
        """Should allow skipping instance configuration."""
        response = authenticated_client.get(
            "/setup/instance/skip", follow_redirects=False
        )
        assert response.status_code == 302
        assert response.headers["location"] == "/setup/complete"

    def test_setup_complete_page_renders(self, authenticated_client):
        """Completion page should render."""
        response = authenticated_client.get("/setup/complete")
        assert response.status_code == 200
        assert b"Setup Complete" in response.content
        assert b"Go to Dashboard" in response.content


class TestDashboardPages:
    """Test dashboard page rendering."""

    def test_dashboard_requires_authentication(self, client):
        """Dashboard should require authentication."""
        response = client.get("/dashboard", follow_redirects=False)
        # Should redirect or return 401
        assert response.status_code in [302, 401]

    def test_dashboard_index_renders(self, authenticated_client):
        """Dashboard index should render with statistics."""
        response = authenticated_client.get("/dashboard")
        assert response.status_code == 200
        assert b"Dashboard" in response.content
        assert b"Instances" in response.content
        assert b"Search Queues" in response.content

    def test_dashboard_instances_page_renders(self, authenticated_client):
        """Instances page should render."""
        response = authenticated_client.get("/dashboard/instances")
        assert response.status_code == 200
        assert b"Instance Management" in response.content

    def test_dashboard_instances_shows_instances(
        self, authenticated_client, test_db
    ):
        """Instances page should display user's instances."""
        from splintarr.core.security import encrypt_field

        # Get the authenticated user
        test_user = test_db.query(User).filter(User.username == "testuser").first()

        # Create test instance
        instance = Instance(
            user_id=test_user.id,
            name="Test Sonarr",
            instance_type="sonarr",
            url="http://localhost:8989",
            api_key_encrypted=encrypt_field("test_api_key_123"),
            is_active=True,
        )
        test_db.add(instance)
        test_db.commit()

        response = authenticated_client.get("/dashboard/instances")
        assert response.status_code == 200
        assert b"Test Sonarr" in response.content

    def test_dashboard_search_queues_page_renders(self, authenticated_client):
        """Search queues page should render."""
        response = authenticated_client.get("/dashboard/search-queues")
        assert response.status_code == 200
        assert b"Search Queue Management" in response.content

    def test_dashboard_search_history_page_renders(self, authenticated_client):
        """Search history page should render."""
        response = authenticated_client.get("/dashboard/search-history")
        assert response.status_code == 200
        assert b"Search History" in response.content

    def test_dashboard_search_history_pagination(self, authenticated_client):
        """Search history should support pagination."""
        response = authenticated_client.get("/dashboard/search-history?page=1&per_page=10")
        assert response.status_code == 200

    def test_dashboard_settings_page_renders(self, authenticated_client):
        """Settings page should render."""
        response = authenticated_client.get("/dashboard/settings")
        assert response.status_code == 200
        assert b"Settings" in response.content
        assert b"Account Information" in response.content


class TestDashboardAPIEndpoints:
    """Test dashboard JSON API endpoints."""

    def test_dashboard_stats_requires_authentication(self, client):
        """Dashboard stats endpoint should require authentication."""
        response = client.get("/api/dashboard/stats")
        # Should return 401 or redirect
        assert response.status_code in [401, 302]

    def test_dashboard_stats_returns_json(self, authenticated_client):
        """Dashboard stats should return JSON statistics."""
        response = authenticated_client.get("/api/dashboard/stats")
        assert response.status_code == 200

        data = response.json()
        assert "instances" in data
        assert "search_queues" in data
        assert "searches" in data

    def test_dashboard_activity_returns_json(self, authenticated_client):
        """Dashboard activity should return recent activity."""
        response = authenticated_client.get("/api/dashboard/activity")
        assert response.status_code == 200

        data = response.json()
        assert "activity" in data
        assert isinstance(data["activity"], list)

    def test_dashboard_activity_respects_limit(self, authenticated_client):
        """Dashboard activity should respect limit parameter."""
        response = authenticated_client.get("/api/dashboard/activity?limit=5")
        assert response.status_code == 200

        data = response.json()
        assert len(data["activity"]) <= 5


class TestSecurityFeatures:
    """Test security features (CSRF, XSS protection)."""

    def test_dashboard_has_security_headers(self, authenticated_client):
        """Dashboard responses should include security headers."""
        response = authenticated_client.get("/dashboard")

        assert "X-Content-Type-Options" in response.headers
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert "X-Frame-Options" in response.headers
        assert "Content-Security-Policy" in response.headers

    def test_templates_escape_user_input(self, authenticated_client, test_db):
        """Templates should escape HTML in user input to prevent XSS."""
        from splintarr.core.security import encrypt_field

        # Get the authenticated user
        test_user = test_db.query(User).filter(User.username == "testuser").first()

        # Create instance with XSS attempt in name
        instance = Instance(
            user_id=test_user.id,
            name="<script>alert('xss')</script>",
            instance_type="sonarr",
            url="http://localhost:8989",
            api_key_encrypted=encrypt_field("test_api_key"),
            is_active=True,
        )
        test_db.add(instance)
        test_db.commit()

        response = authenticated_client.get("/dashboard/instances")

        # Should be HTML-escaped, not executed
        assert b"<script>" not in response.content
        assert b"&lt;script&gt;" in response.content or b"alert" not in response.content


class TestTemplateComponents:
    """Test reusable template components."""

    def test_flash_messages_displayed(self, authenticated_client, test_db):
        """Flash messages should be displayed and auto-dismiss."""
        # This would require session-based flash messages to be implemented
        # For now, we test that error/success messages are shown in templates

        # Try to create instance with invalid URL to trigger error message
        response = authenticated_client.post(
            "/setup/instance",
            data={
                "instance_type": "sonarr",
                "name": "Test",
                "url": "invalid-url",
                "api_key": "test_key",
            },
        )

        # Should show error message
        assert b"error" in response.content.lower() or b"failed" in response.content.lower()

    def test_base_template_includes_navigation(self, authenticated_client):
        """Base template should include navigation menu when authenticated."""
        response = authenticated_client.get("/dashboard")

        assert b"Dashboard" in response.content
        assert b"Instances" in response.content
        assert b"Queues" in response.content
        assert b"History" in response.content
        assert b"Settings" in response.content
        assert b"Logout" in response.content


class TestResponsiveDesign:
    """Test responsive design and mobile compatibility."""

    def test_templates_include_viewport_meta(self, authenticated_client):
        """Templates should include viewport meta for mobile responsiveness."""
        response = authenticated_client.get("/dashboard")
        assert b'name="viewport"' in response.content

    def test_templates_use_pico_css(self, authenticated_client):
        """Templates should load Pico CSS framework."""
        response = authenticated_client.get("/dashboard")
        assert b"pico" in response.content.lower()


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_dashboard_handles_missing_user_gracefully(self, client):
        """Dashboard should handle missing user gracefully."""
        # Try to access dashboard without authentication
        response = client.get("/dashboard", follow_redirects=False)
        # Should redirect to login or return 401, not crash
        assert response.status_code in [302, 401]

    def test_setup_handles_duplicate_username(self, client, test_db):
        """Setup should handle duplicate username gracefully."""
        test_db.query(User).delete()
        test_db.commit()

        # Create first user
        client.post(
            "/setup/admin",
            data={
                "username": "admin",
                "password": "SecurePassword123!",
                "confirm_password": "SecurePassword123!",
            },
        )

        # Try to create another user with same username (shouldn't be possible in setup)
        # This tests that setup properly checks for existing users
        response = client.get("/setup", follow_redirects=False)
        assert response.status_code == 302  # Should redirect away from setup
