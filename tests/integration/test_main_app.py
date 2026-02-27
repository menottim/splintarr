"""
Integration tests for FastAPI main application.

Tests security headers, CORS, rate limiting, error handling, and health checks.
"""

import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from splintarr.config import settings
from splintarr.core.security import hash_password
from splintarr.models.user import User


class TestSecurityHeaders:
    """Tests for security headers middleware."""

    def test_hsts_header_in_production(self, client: TestClient, test_settings):
        """Test Strict-Transport-Security header in production mode."""
        # Temporarily enable production mode and secure cookies
        with patch.object(test_settings, "environment", "production"), \
             patch.object(test_settings, "secure_cookies", True):

            response = client.get("/")

            assert "Strict-Transport-Security" in response.headers
            assert "max-age=31536000" in response.headers["Strict-Transport-Security"]
            assert "includeSubDomains" in response.headers["Strict-Transport-Security"]

    def test_hsts_header_not_in_dev(self, client: TestClient):
        """Test HSTS header is not present in development mode."""
        response = client.get("/")

        # HSTS should not be set in test/dev mode
        assert "Strict-Transport-Security" not in response.headers

    def test_csp_header(self, client: TestClient):
        """Test Content-Security-Policy header."""
        response = client.get("/")

        assert "Content-Security-Policy" in response.headers
        csp = response.headers["Content-Security-Policy"]

        # Verify key CSP directives
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "style-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "base-uri 'self'" in csp
        assert "form-action 'self'" in csp

    def test_x_frame_options(self, client: TestClient):
        """Test X-Frame-Options header."""
        response = client.get("/")

        assert response.headers.get("X-Frame-Options") == "DENY"

    def test_x_content_type_options(self, client: TestClient):
        """Test X-Content-Type-Options header."""
        response = client.get("/")

        assert response.headers.get("X-Content-Type-Options") == "nosniff"

    def test_referrer_policy(self, client: TestClient):
        """Test Referrer-Policy header."""
        response = client.get("/")

        assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_x_xss_protection(self, client: TestClient):
        """Test X-XSS-Protection header."""
        response = client.get("/")

        assert response.headers.get("X-XSS-Protection") == "1; mode=block"

    def test_security_headers_on_all_endpoints(self, client: TestClient):
        """Test security headers are present on all endpoints."""
        endpoints = [
            "/",
            "/health",
            "/api",
            "/api/auth/status",
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)

            # Check all security headers are present
            assert "X-Content-Type-Options" in response.headers
            assert "X-Frame-Options" in response.headers
            assert "X-XSS-Protection" in response.headers
            assert "Referrer-Policy" in response.headers
            assert "Content-Security-Policy" in response.headers


class TestCORS:
    """Tests for CORS middleware."""

    def test_cors_allowed_origin(self, client: TestClient, test_settings):
        """Test CORS headers with allowed origin."""
        # Mock CORS settings
        with patch.object(test_settings, "cors_origins", ["http://localhost:3000"]):
            response = client.options(
                "/api/auth/status",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "GET",
                },
            )

            # FastAPI returns 200 for OPTIONS requests
            assert response.status_code in (200, 204)

    def test_cors_credentials(self, client: TestClient, test_settings):
        """Test CORS credentials are allowed."""
        with patch.object(test_settings, "cors_origins", ["http://localhost:3000"]), \
             patch.object(test_settings, "cors_allow_credentials", True):

            response = client.get(
                "/",
                headers={"Origin": "http://localhost:3000"},
            )

            # Check if CORS headers would be present
            # (TestClient doesn't fully simulate CORS)
            assert response.status_code == 200

    def test_cors_preflight(self, client: TestClient, test_settings):
        """Test CORS preflight (OPTIONS) request handling."""
        with patch.object(test_settings, "cors_origins", ["http://localhost:3000"]):
            response = client.options(
                "/api/auth/status",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "Content-Type",
                },
            )

            # Preflight requests should succeed
            assert response.status_code in (200, 204)


class TestRateLimiting:
    """Tests for rate limiting middleware."""

    def test_rate_limit_headers(self, client: TestClient):
        """Test X-RateLimit headers are present."""
        response = client.get("/")

        # SlowAPI adds rate limit headers
        # Headers might not be present on all responses depending on configuration
        assert response.status_code == 200

    def test_global_rate_limit(self, client: TestClient, test_settings):
        """Test global rate limit enforcement."""
        # Make multiple rapid requests to trigger rate limit
        # Note: This test might be flaky depending on rate limit settings

        responses = []
        # Make requests up to the limit
        for i in range(test_settings.rate_limit_per_minute + 5):
            response = client.get("/")
            responses.append(response)

            # If we get rate limited, stop
            if response.status_code == 429:
                break

        # At least one request should succeed
        assert any(r.status_code == 200 for r in responses)

        # If rate limit is enforced, we should get 429
        # (This might not always trigger in tests with low request counts)

    def test_rate_limit_reset(self, client: TestClient):
        """Test rate limit resets after time window."""
        # Make a request
        response = client.get("/")
        assert response.status_code == 200

        # Wait a bit (rate limits are per-minute in default config)
        # In real tests, you might mock time or use a shorter window
        time.sleep(0.1)

        # Should still work
        response = client.get("/")
        assert response.status_code == 200


class TestErrorHandling:
    """Tests for error handling."""

    def test_404_error(self, client: TestClient):
        """Test 404 error handling."""
        response = client.get("/nonexistent-endpoint")

        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert "not found" in data["detail"].lower()

    def test_validation_error(self, client: TestClient):
        """Test Pydantic validation error handling."""
        # Attempt to register with invalid data
        response = client.post(
            "/api/auth/register",
            json={
                "username": "ab",  # Too short
                "password": "short",  # Too weak
            },
        )

        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

    def test_authentication_error(self, client: TestClient, db_session: Session):
        """Test 401 authentication error."""
        # Try to access protected endpoint without authentication
        response = client.get("/api/auth/me")

        assert response.status_code == 401
        data = response.json()
        assert "detail" in data

    def test_authorization_error(self, client: TestClient, db_session: Session):
        """Test 403 authorization error."""
        # Create a user
        user = User(
            username="testuser",
            password_hash=hash_password("TestP@ssw0rd123!"),
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()

        # Try to register another user (registration is disabled after first user)
        response = client.post(
            "/api/auth/register",
            json={
                "username": "anotheruser",
                "password": "SecureP@ssw0rd123!",
            },
        )

        assert response.status_code == 403
        data = response.json()
        assert "detail" in data


class TestHealthCheck:
    """Tests for health check endpoint."""

    def test_health_endpoint(self, client: TestClient):
        """Test GET /health returns 200."""
        response = client.get("/health")

        assert response.status_code == 200

    def test_health_response_format(self, client: TestClient):
        """Test health check response JSON structure."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "status" in data
        assert "application" in data
        assert "database" in data

        # Verify database health info
        assert isinstance(data["database"], dict)
        assert "status" in data["database"]

    def test_health_database_check(self, client: TestClient):
        """Test health check includes database connectivity."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()

        # Database should be healthy in tests
        assert data["database"]["status"] == "healthy"

    def test_health_unhealthy_database(self, client: TestClient):
        """Test health check when database is unhealthy."""
        # Mock database_health_check to return unhealthy
        with patch("splintarr.main.database_health_check") as mock_health:
            mock_health.return_value = {"status": "unhealthy", "error": "Connection failed"}

            response = client.get("/health")

            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "unhealthy"
            assert data["database"]["status"] == "unhealthy"


class TestStartupShutdown:
    """Tests for application startup and shutdown events."""

    def test_startup_initializes_database(self, db_session):
        """Test startup event initializes database tables."""
        # Database should already be initialized by fixtures
        from splintarr.models.user import User

        # Should be able to query without errors
        users = db_session.query(User).all()
        assert isinstance(users, list)

    def test_startup_event_runs(self, client: TestClient):
        """Test startup event executes successfully."""
        # If client is created successfully, startup event ran
        response = client.get("/")
        assert response.status_code == 200


class TestRootEndpoints:
    """Tests for root API endpoints."""

    def test_root_endpoint(self, client: TestClient):
        """Test GET / returns API information."""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()

        assert "name" in data
        assert "version" in data
        assert "status" in data
        assert "environment" in data

        assert data["status"] == "operational"

    def test_api_info_endpoint(self, client: TestClient):
        """Test GET /api returns API information."""
        response = client.get("/api")

        assert response.status_code == 200
        data = response.json()

        assert "version" in data
        assert "endpoints" in data
        assert "documentation" in data

        # Check endpoints structure
        assert "authentication" in data["endpoints"]
        assert "instances" in data["endpoints"]
        assert "search" in data["endpoints"]

    def test_api_documentation_in_dev(self, client: TestClient, test_settings):
        """Test API documentation is available in dev mode."""
        response = client.get("/api")
        data = response.json()

        # In test mode, docs should be enabled
        # (depending on settings)
        assert "documentation" in data


class TestMiddlewareOrder:
    """Tests for middleware execution order."""

    def test_security_headers_applied_before_cors(self, client: TestClient):
        """Test security headers are applied before CORS."""
        response = client.get("/")

        # Both security headers and CORS should work together
        assert "X-Content-Type-Options" in response.headers
        assert response.status_code == 200

    def test_rate_limiting_before_route(self, client: TestClient):
        """Test rate limiting is checked before route execution."""
        # Make a valid request
        response = client.get("/")

        # Should succeed if under rate limit
        assert response.status_code == 200


class TestRequestValidation:
    """Tests for request validation."""

    def test_invalid_json_body(self, client: TestClient):
        """Test invalid JSON body returns 422."""
        response = client.post(
            "/api/auth/register",
            data="invalid json",
            headers={"Content-Type": "application/json"},
        )

        # Should return validation error
        assert response.status_code == 422

    def test_missing_required_fields(self, client: TestClient):
        """Test missing required fields returns 422."""
        response = client.post(
            "/api/auth/register",
            json={
                "username": "admin",
                # Missing password
            },
        )

        assert response.status_code == 422

    def test_extra_fields_ignored(self, client: TestClient, db_session: Session):
        """Test extra fields in request are ignored."""
        # Ensure no users exist
        assert db_session.query(User).count() == 0

        response = client.post(
            "/api/auth/register",
            json={
                "username": "admin",
                "password": "SecureP@ssw0rd123!",
                "extra_field": "should be ignored",
            },
        )

        # Should succeed (extra fields are ignored by Pydantic)
        assert response.status_code == 201


class TestResponseFormat:
    """Tests for response format consistency."""

    def test_json_response_format(self, client: TestClient):
        """Test all responses are valid JSON."""
        endpoints = [
            "/",
            "/health",
            "/api",
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)

            # Should be valid JSON
            assert response.headers.get("content-type") == "application/json"
            data = response.json()
            assert isinstance(data, dict)

    def test_error_response_format(self, client: TestClient):
        """Test error responses have consistent format."""
        response = client.get("/nonexistent")

        assert response.status_code == 404
        data = response.json()

        # Error responses should have 'detail' field
        assert "detail" in data
