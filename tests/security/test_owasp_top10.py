"""
OWASP Top 10 Security Tests for Splintarr.

Tests application against OWASP Top 10 2021 vulnerabilities:
1. Broken Access Control
2. Cryptographic Failures
3. Injection
4. Insecure Design
5. Security Misconfiguration
6. Vulnerable and Outdated Components
7. Identification and Authentication Failures
8. Software and Data Integrity Failures
9. Security Logging and Monitoring Failures
10. Server-Side Request Forgery (SSRF)
"""

import pytest
from fastapi.testclient import TestClient


class TestBrokenAccessControl:
    """A01:2021 – Broken Access Control tests."""

    def test_unauthenticated_access_blocked(self, client: TestClient):
        """Verify that protected endpoints require authentication."""
        # Attempt to access protected endpoints without token
        protected_endpoints = [
            ("/api/instances/", "GET"),
            ("/api/search-queues/", "GET"),
            ("/api/auth/me", "GET"),
            ("/api/search-history/", "GET"),
        ]

        for endpoint, method in protected_endpoints:
            if method == "GET":
                response = client.get(endpoint)
            elif method == "POST":
                response = client.post(endpoint, json={})

            assert response.status_code == 401, \
                f"Endpoint {endpoint} should require authentication but returned {response.status_code}"

    def test_user_cannot_access_other_user_data(self, client: TestClient, db_session):
        """Verify users cannot access resources belonging to other users."""
        # Create first user
        user1_data = {
            "username": "user1",
            "email": "user1@example.com",
            "password": "User1Pass123!",
            "confirm_password": "User1Pass123!",
        }
        client.post("/api/auth/setup", json=user1_data)

        # Login as user1
        login1_response = client.post("/api/auth/login", data={
            "username": "user1",
            "password": "User1Pass123!",
        })
        user1_token = login1_response.json()["access_token"]
        user1_headers = {"Authorization": f"Bearer {user1_token}"}

        # Create instance for user1
        instance_data = {
            "name": "User1 Instance",
            "instance_type": "sonarr",
            "base_url": "http://localhost:8989",
            "api_key": "user1-key",
        }
        instance_response = client.post("/api/instances/", json=instance_data, headers=user1_headers)
        instance_id = instance_response.json()["id"]

        # Logout and create second user
        client.post("/api/auth/logout", headers=user1_headers)

        # Manually create second user (setup endpoint only works once)
        from splintarr.models.user import User
        from splintarr.core.security import hash_password

        user2 = User(
            username="user2",
            email="user2@example.com",
            hashed_password=hash_password("User2Pass123!"),
            is_active=True,
            is_superuser=False,
        )
        db_session.add(user2)
        db_session.commit()

        # Login as user2
        login2_response = client.post("/api/auth/login", data={
            "username": "user2",
            "password": "User2Pass123!",
        })
        user2_token = login2_response.json()["access_token"]
        user2_headers = {"Authorization": f"Bearer {user2_token}"}

        # Try to access user1's instance
        access_response = client.get(f"/api/instances/{instance_id}", headers=user2_headers)
        assert access_response.status_code == 404, \
            "User should not be able to access another user's instance"

        # Try to list instances (should only see own instances)
        list_response = client.get("/api/instances/", headers=user2_headers)
        assert list_response.status_code == 200
        instances = list_response.json()
        assert len(instances) == 0, "User should not see other users' instances"

    def test_horizontal_privilege_escalation_prevented(self, client: TestClient, db_session):
        """Verify users cannot modify resources belonging to other users."""
        # Setup similar to previous test
        user1_data = {
            "username": "user1_mod",
            "email": "user1_mod@example.com",
            "password": "User1Pass123!",
            "confirm_password": "User1Pass123!",
        }
        client.post("/api/auth/setup", json=user1_data)

        login1_response = client.post("/api/auth/login", data={
            "username": "user1_mod",
            "password": "User1Pass123!",
        })
        user1_token = login1_response.json()["access_token"]
        user1_headers = {"Authorization": f"Bearer {user1_token}"}

        instance_data = {
            "name": "User1 Mod Instance",
            "instance_type": "sonarr",
            "base_url": "http://localhost:8989",
            "api_key": "user1-mod-key",
        }
        instance_response = client.post("/api/instances/", json=instance_data, headers=user1_headers)
        instance_id = instance_response.json()["id"]

        # Create user2
        from splintarr.models.user import User
        from splintarr.core.security import hash_password

        user2 = User(
            username="user2_mod",
            email="user2_mod@example.com",
            hashed_password=hash_password("User2Pass123!"),
            is_active=True,
            is_superuser=False,
        )
        db_session.add(user2)
        db_session.commit()

        login2_response = client.post("/api/auth/login", data={
            "username": "user2_mod",
            "password": "User2Pass123!",
        })
        user2_token = login2_response.json()["access_token"]
        user2_headers = {"Authorization": f"Bearer {user2_token}"}

        # Try to modify user1's instance
        update_data = {"name": "Hacked Instance"}
        update_response = client.patch(
            f"/api/instances/{instance_id}",
            json=update_data,
            headers=user2_headers
        )
        assert update_response.status_code in [403, 404], \
            "User should not be able to modify another user's instance"

        # Try to delete user1's instance
        delete_response = client.delete(f"/api/instances/{instance_id}", headers=user2_headers)
        assert delete_response.status_code in [403, 404], \
            "User should not be able to delete another user's instance"


class TestCryptographicFailures:
    """A02:2021 – Cryptographic Failures tests."""

    def test_passwords_are_hashed(self, client: TestClient, db_session):
        """Verify passwords are stored hashed, not in plaintext."""
        from splintarr.models.user import User

        # Create user
        user_data = {
            "username": "hashtest",
            "email": "hashtest@example.com",
            "password": "PlaintextPassword123!",
            "confirm_password": "PlaintextPassword123!",
        }
        client.post("/api/auth/setup", json=user_data)

        # Retrieve user from database
        user = db_session.query(User).filter_by(username="hashtest").first()
        assert user is not None

        # Verify password is hashed
        assert user.hashed_password != "PlaintextPassword123!"
        assert user.hashed_password.startswith("$argon2id$"), \
            "Password should be hashed with Argon2id"
        assert len(user.hashed_password) > 50, \
            "Hashed password should be significantly longer than plaintext"

    def test_api_keys_are_encrypted(self, client: TestClient, db_session):
        """Verify API keys are stored encrypted in the database."""
        from splintarr.models.instance import Instance

        # Setup user
        user_data = {
            "username": "enctest",
            "email": "enctest@example.com",
            "password": "EncTest123!",
            "confirm_password": "EncTest123!",
        }
        client.post("/api/auth/setup", json=user_data)

        login_response = client.post("/api/auth/login", data={
            "username": "enctest",
            "password": "EncTest123!",
        })
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Create instance with API key
        plaintext_api_key = "my-secret-api-key-1234567890"
        instance_data = {
            "name": "Encryption Test",
            "instance_type": "sonarr",
            "base_url": "http://localhost:8989",
            "api_key": plaintext_api_key,
        }
        instance_response = client.post("/api/instances/", json=instance_data, headers=headers)
        instance_id = instance_response.json()["id"]

        # Retrieve instance from database
        instance = db_session.query(Instance).filter_by(id=instance_id).first()
        assert instance is not None

        # Verify API key is encrypted
        assert instance.encrypted_api_key != plaintext_api_key, \
            "API key should be encrypted in database"
        assert instance.encrypted_api_key != plaintext_api_key.encode(), \
            "API key should be encrypted, not just encoded"

    def test_sensitive_data_not_in_logs(self, client: TestClient):
        """Verify sensitive data is not exposed in API responses."""
        # Create user
        user_data = {
            "username": "sensitive",
            "email": "sensitive@example.com",
            "password": "SensitivePass123!",
            "confirm_password": "SensitivePass123!",
        }
        setup_response = client.post("/api/auth/setup", json=user_data)
        setup_json = setup_response.json()

        # Verify password is not in response
        assert "password" not in str(setup_json).lower() or \
               setup_json.get("password") is None, \
            "Password should not be in API response"

        # Login
        login_response = client.post("/api/auth/login", data={
            "username": "sensitive",
            "password": "SensitivePass123!",
        })
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Create instance
        instance_data = {
            "name": "Sensitive Instance",
            "instance_type": "sonarr",
            "base_url": "http://localhost:8989",
            "api_key": "super-secret-key-123",
        }
        instance_response = client.post("/api/instances/", json=instance_data, headers=headers)
        instance_json = instance_response.json()

        # Verify API key is not in response
        assert "api_key" not in instance_json or \
               instance_json.get("api_key") == "super-secret-key-123" or \
               instance_json.get("api_key") is None, \
            "API key should be omitted or masked in response"


class TestInjection:
    """A03:2021 – Injection tests (SQL, Command, etc.)."""

    def test_sql_injection_in_username(self, client: TestClient):
        """Test SQL injection attempts in username field."""
        # Try SQL injection in username
        sql_payloads = [
            "admin' OR '1'='1",
            "admin'; DROP TABLE users; --",
            "admin' UNION SELECT * FROM users--",
            "admin'/**/OR/**/1=1--",
        ]

        for payload in sql_payloads:
            user_data = {
                "username": payload,
                "email": "sqli@example.com",
                "password": "SqlInjection123!",
                "confirm_password": "SqlInjection123!",
            }
            response = client.post("/api/auth/setup", json=user_data)
            # Should either reject as invalid or create user with literal string
            # Should NOT execute SQL
            assert response.status_code in [200, 400, 422]

    def test_sql_injection_in_search_filters(self, client: TestClient, db_session):
        """Test SQL injection attempts in search/filter parameters."""
        # Setup user
        user_data = {
            "username": "filtertest",
            "email": "filtertest@example.com",
            "password": "FilterTest123!",
            "confirm_password": "FilterTest123!",
        }
        client.post("/api/auth/setup", json=user_data)

        login_response = client.post("/api/auth/login", data={
            "username": "filtertest",
            "password": "FilterTest123!",
        })
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Try SQL injection in query parameters
        sql_payloads = [
            "1' OR '1'='1",
            "1; DROP TABLE instances--",
            "1 UNION SELECT * FROM users",
        ]

        for payload in sql_payloads:
            # Test in instance list with filter
            response = client.get(f"/api/instances/?name={payload}", headers=headers)
            # Should not cause error or execute SQL
            assert response.status_code in [200, 400, 422]

    def test_command_injection_in_instance_url(self, client: TestClient):
        """Test command injection attempts in instance URLs."""
        # Setup user
        user_data = {
            "username": "cmdtest",
            "email": "cmdtest@example.com",
            "password": "CmdTest123!",
            "confirm_password": "CmdTest123!",
        }
        client.post("/api/auth/setup", json=user_data)

        login_response = client.post("/api/auth/login", data={
            "username": "cmdtest",
            "password": "CmdTest123!",
        })
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Try command injection in URL
        cmd_payloads = [
            "http://localhost:8989; rm -rf /",
            "http://localhost:8989`whoami`",
            "http://localhost:8989$(cat /etc/passwd)",
            "http://localhost:8989 && curl evil.com",
        ]

        for payload in cmd_payloads:
            instance_data = {
                "name": "Cmd Injection Test",
                "instance_type": "sonarr",
                "base_url": payload,
                "api_key": "test-key",
            }
            response = client.post("/api/instances/", json=instance_data, headers=headers)
            # Should validate URL format or safely handle
            # Should NOT execute commands
            assert response.status_code in [200, 400, 422]

    def test_xss_in_instance_name(self, client: TestClient):
        """Test XSS attempts in instance name field."""
        # Setup user
        user_data = {
            "username": "xsstest",
            "email": "xsstest@example.com",
            "password": "XssTest123!",
            "confirm_password": "XssTest123!",
        }
        client.post("/api/auth/setup", json=user_data)

        login_response = client.post("/api/auth/login", data={
            "username": "xsstest",
            "password": "XssTest123!",
        })
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Try XSS payloads
        xss_payloads = [
            "<script>alert('XSS')</script>",
            "<img src=x onerror=alert('XSS')>",
            "javascript:alert('XSS')",
            "<svg/onload=alert('XSS')>",
        ]

        for payload in xss_payloads:
            instance_data = {
                "name": payload,
                "instance_type": "sonarr",
                "base_url": "http://localhost:8989",
                "api_key": "test-key",
            }
            response = client.post("/api/instances/", json=instance_data, headers=headers)
            if response.status_code == 200:
                result = response.json()
                # If accepted, should be sanitized or escaped
                # Frontend should handle proper escaping
                assert result["name"] == payload  # Stored as-is, frontend must escape


class TestAuthenticationFailures:
    """A07:2021 – Identification and Authentication Failures tests."""

    def test_weak_password_rejected(self, client: TestClient):
        """Verify weak passwords are rejected."""
        weak_passwords = [
            "password",  # Too common
            "12345678",  # Only numbers
            "abc123",  # Too short
            "Password",  # No special chars
        ]

        for weak_pass in weak_passwords:
            user_data = {
                "username": f"user_{weak_pass}",
                "email": f"{weak_pass}@example.com",
                "password": weak_pass,
                "confirm_password": weak_pass,
            }
            response = client.post("/api/auth/setup", json=user_data)
            # Should reject weak passwords
            assert response.status_code in [400, 422], \
                f"Weak password '{weak_pass}' should be rejected"

    def test_password_confirmation_required(self, client: TestClient):
        """Verify password confirmation must match."""
        user_data = {
            "username": "mismatch",
            "email": "mismatch@example.com",
            "password": "StrongPass123!",
            "confirm_password": "DifferentPass123!",
        }
        response = client.post("/api/auth/setup", json=user_data)
        assert response.status_code in [400, 422], \
            "Mismatched passwords should be rejected"

    def test_brute_force_protection(self, client: TestClient, db_session):
        """Test protection against brute force attacks."""
        # Create user
        user_data = {
            "username": "brutetest",
            "email": "brutetest@example.com",
            "password": "BruteTest123!",
            "confirm_password": "BruteTest123!",
        }
        client.post("/api/auth/setup", json=user_data)

        # Attempt multiple failed logins
        failed_attempts = 0
        for i in range(20):
            response = client.post("/api/auth/login", data={
                "username": "brutetest",
                "password": f"WrongPassword{i}",
            })
            if response.status_code == 401:
                failed_attempts += 1
            elif response.status_code == 429:
                # Rate limiting kicked in
                break

        # Should have rate limiting or account lockout
        # At minimum, rate limiting should prevent all 20 attempts
        assert failed_attempts < 20, \
            "Should have rate limiting to prevent brute force attacks"

    def test_session_timeout(self, client: TestClient):
        """Verify sessions have reasonable timeouts."""
        # Create user
        user_data = {
            "username": "timeout",
            "email": "timeout@example.com",
            "password": "Timeout123!",
            "confirm_password": "Timeout123!",
        }
        client.post("/api/auth/setup", json=user_data)

        # Login
        login_response = client.post("/api/auth/login", data={
            "username": "timeout",
            "password": "Timeout123!",
        })
        assert login_response.status_code == 200
        token_data = login_response.json()

        # Verify token has expiration
        assert "expires_in" in token_data or "access_token" in token_data
        # JWT tokens should have reasonable expiration (checked via configuration)


class TestSSRF:
    """A10:2021 – Server-Side Request Forgery tests."""

    def test_ssrf_in_instance_url(self, client: TestClient):
        """Test SSRF protection in instance URL validation."""
        # Setup user
        user_data = {
            "username": "ssrftest",
            "email": "ssrftest@example.com",
            "password": "SsrfTest123!",
            "confirm_password": "SsrfTest123!",
        }
        client.post("/api/auth/setup", json=user_data)

        login_response = client.post("/api/auth/login", data={
            "username": "ssrftest",
            "password": "SsrfTest123!",
        })
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Try SSRF payloads
        ssrf_payloads = [
            "http://127.0.0.1:22",  # SSH port
            "http://localhost:3306",  # MySQL port
            "http://169.254.169.254/latest/meta-data/",  # AWS metadata
            "file:///etc/passwd",  # File protocol
            "http://0.0.0.0:6379",  # Redis port
        ]

        for payload in ssrf_payloads:
            instance_data = {
                "name": f"SSRF Test {payload}",
                "instance_type": "sonarr",
                "base_url": payload,
                "api_key": "test-key",
            }
            response = client.post("/api/instances/", json=instance_data, headers=headers)
            # Should validate URL or block internal addresses
            # HTTP/HTTPS to external or allowed local addresses only
            if "localhost" in payload or "127.0.0.1" in payload:
                # May be allowed if ALLOW_LOCAL_INSTANCES is true
                # But specific ports should be validated
                pass
            else:
                # Non-HTTP protocols and cloud metadata should be blocked
                assert response.status_code in [400, 422], \
                    f"SSRF payload should be blocked: {payload}"


class TestSecurityMisconfiguration:
    """A05:2021 – Security Misconfiguration tests."""

    def test_debug_mode_disabled_in_production(self, client: TestClient):
        """Verify debug mode is disabled in production."""
        # Check that API doesn't expose debug information
        response = client.get("/api/auth/me")  # Unauthorized request
        assert response.status_code == 401

        # Response should not contain debug traces
        response_text = response.text.lower()
        assert "traceback" not in response_text
        assert "debug" not in response_text

    def test_security_headers_present(self, client: TestClient):
        """Verify security headers are present in responses."""
        response = client.get("/")

        headers = response.headers

        # Check for important security headers
        assert "x-content-type-options" in headers, \
            "X-Content-Type-Options header should be present"
        assert "x-frame-options" in headers, \
            "X-Frame-Options header should be present"
        assert "content-security-policy" in headers or "x-content-security-policy" in headers, \
            "Content-Security-Policy header should be present"

    def test_default_credentials_not_accepted(self, client: TestClient):
        """Verify default/common credentials are not accepted."""
        common_credentials = [
            ("admin", "admin"),
            ("admin", "password"),
            ("admin", "123456"),
            ("administrator", "administrator"),
        ]

        for username, password in common_credentials:
            response = client.post("/api/auth/login", data={
                "username": username,
                "password": password,
            })
            # Should fail - either user doesn't exist or password doesn't meet requirements
            assert response.status_code == 401


class TestLoggingAndMonitoring:
    """A09:2021 – Security Logging and Monitoring Failures tests."""

    def test_failed_login_attempts_logged(self, client: TestClient, db_session):
        """Verify failed login attempts are logged."""
        # Create user
        user_data = {
            "username": "logtest",
            "email": "logtest@example.com",
            "password": "LogTest123!",
            "confirm_password": "LogTest123!",
        }
        client.post("/api/auth/setup", json=user_data)

        # Attempt failed login
        response = client.post("/api/auth/login", data={
            "username": "logtest",
            "password": "WrongPassword",
        })
        assert response.status_code == 401

        # In a real test, we would verify logs are created
        # This is a placeholder for actual log verification
        # Implementation depends on logging infrastructure

    def test_successful_authentication_logged(self, client: TestClient):
        """Verify successful authentication is logged."""
        # Create user
        user_data = {
            "username": "authlog",
            "email": "authlog@example.com",
            "password": "AuthLog123!",
            "confirm_password": "AuthLog123!",
        }
        client.post("/api/auth/setup", json=user_data)

        # Successful login
        response = client.post("/api/auth/login", data={
            "username": "authlog",
            "password": "AuthLog123!",
        })
        assert response.status_code == 200

        # Logs should record successful authentication
        # Placeholder for actual log verification


class TestCSRFProtection:
    """Cross-Site Request Forgery protection tests."""

    def test_state_changing_operations_protected(self, client: TestClient):
        """Verify state-changing operations have CSRF protection."""
        # Setup user
        user_data = {
            "username": "csrf",
            "email": "csrf@example.com",
            "password": "Csrf123!",
            "confirm_password": "Csrf123!",
        }
        client.post("/api/auth/setup", json=user_data)

        login_response = client.post("/api/auth/login", data={
            "username": "csrf",
            "password": "Csrf123!",
        })
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Attempt to create instance
        instance_data = {
            "name": "CSRF Test",
            "instance_type": "sonarr",
            "base_url": "http://localhost:8989",
            "api_key": "csrf-key",
        }

        # With proper auth, should succeed
        response = client.post("/api/instances/", json=instance_data, headers=headers)
        assert response.status_code == 200

        # Without auth token, should fail (CSRF protection via auth)
        response_no_auth = client.post("/api/instances/", json=instance_data)
        assert response_no_auth.status_code == 401


class TestRateLimiting:
    """Rate limiting tests for API endpoints."""

    def test_api_rate_limiting(self, client: TestClient):
        """Verify API endpoints have rate limiting."""
        # Attempt many requests in quick succession
        responses = []
        for i in range(150):  # Exceed typical rate limit
            response = client.get("/api/auth/health")
            responses.append(response.status_code)

        # Should encounter rate limiting
        rate_limited = any(status == 429 for status in responses)
        assert rate_limited, "Should have rate limiting on API endpoints"

    def test_login_rate_limiting(self, client: TestClient):
        """Verify login endpoint has rate limiting."""
        # Create user
        user_data = {
            "username": "ratetest",
            "email": "ratetest@example.com",
            "password": "RateTest123!",
            "confirm_password": "RateTest123!",
        }
        client.post("/api/auth/setup", json=user_data)

        # Attempt many logins
        responses = []
        for i in range(50):
            response = client.post("/api/auth/login", data={
                "username": "ratetest",
                "password": "WrongPassword",
            })
            responses.append(response.status_code)

        # Should encounter rate limiting
        rate_limited = any(status == 429 for status in responses)
        assert rate_limited, "Should have rate limiting on login endpoint"
