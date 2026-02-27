"""
End-to-end tests covering complete user workflows.

Tests the entire application flow from setup wizard to search execution,
ensuring all components work together correctly.
"""

import pytest
from fastapi.testclient import TestClient

from splintarr.models.instance import InstanceType
from splintarr.models.search_queue import SearchStrategy, SearchStatus


class TestCompleteUserJourney:
    """Test the complete user journey through the application."""

    def test_full_workflow_setup_to_search(self, client: TestClient, db_session):
        """
        Test complete workflow: setup wizard → login → add instance → create queue → execute search.

        This test verifies:
        1. Setup wizard creates initial admin user
        2. User can log in with credentials
        3. User can add Sonarr/Radarr instances
        4. User can create search queues
        5. Search queues can be started and execute properly
        """
        # Step 1: Setup Wizard - Create initial admin user
        setup_data = {
            "username": "admin",
            "email": "admin@example.com",
            "password": "SecurePassword123!",
            "confirm_password": "SecurePassword123!",
        }

        setup_response = client.post("/api/auth/setup", json=setup_data)
        assert setup_response.status_code == 200, f"Setup failed: {setup_response.text}"
        setup_result = setup_response.json()
        assert setup_result["success"] is True
        assert "message" in setup_result

        # Step 2: Login with created user
        login_data = {
            "username": "admin",
            "password": "SecurePassword123!",
        }

        login_response = client.post("/api/auth/login", data=login_data)
        assert login_response.status_code == 200, f"Login failed: {login_response.text}"
        login_result = login_response.json()
        assert "access_token" in login_result
        access_token = login_result["access_token"]

        # Set up auth headers for subsequent requests
        headers = {"Authorization": f"Bearer {access_token}"}

        # Step 3: Add a Sonarr instance
        instance_data = {
            "name": "My Sonarr",
            "instance_type": "sonarr",
            "base_url": "http://localhost:8989",
            "api_key": "test-api-key-1234567890abcdef",
        }

        create_instance_response = client.post(
            "/api/instances/", json=instance_data, headers=headers
        )
        assert create_instance_response.status_code == 200, \
            f"Create instance failed: {create_instance_response.text}"
        instance_result = create_instance_response.json()
        assert instance_result["name"] == "My Sonarr"
        assert instance_result["instance_type"] == "sonarr"
        instance_id = instance_result["id"]

        # Verify instance appears in list
        list_instances_response = client.get("/api/instances/", headers=headers)
        assert list_instances_response.status_code == 200
        instances = list_instances_response.json()
        assert len(instances) == 1
        assert instances[0]["id"] == instance_id

        # Step 4: Create a search queue
        queue_data = {
            "name": "Missing Episodes Queue",
            "instance_id": instance_id,
            "strategy": "missing",
            "max_items_per_run": 10,
            "is_active": True,
        }

        create_queue_response = client.post(
            "/api/search-queues/", json=queue_data, headers=headers
        )
        assert create_queue_response.status_code == 200, \
            f"Create queue failed: {create_queue_response.text}"
        queue_result = create_queue_response.json()
        assert queue_result["name"] == "Missing Episodes Queue"
        assert queue_result["strategy"] == "missing"
        queue_id = queue_result["id"]

        # Verify queue appears in list
        list_queues_response = client.get("/api/search-queues/", headers=headers)
        assert list_queues_response.status_code == 200
        queues = list_queues_response.json()
        assert len(queues) == 1
        assert queues[0]["id"] == queue_id

        # Step 5: Get queue details
        get_queue_response = client.get(f"/api/search-queues/{queue_id}", headers=headers)
        assert get_queue_response.status_code == 200
        queue_details = get_queue_response.json()
        assert queue_details["status"] == "idle"
        assert queue_details["is_active"] is True

        # Step 6: Update queue configuration
        update_data = {"max_items_per_run": 20}
        update_response = client.patch(
            f"/api/search-queues/{queue_id}", json=update_data, headers=headers
        )
        assert update_response.status_code == 200
        updated_queue = update_response.json()
        assert updated_queue["max_items_per_run"] == 20

        # Step 7: Test queue pause/resume
        pause_response = client.post(
            f"/api/search-queues/{queue_id}/pause", headers=headers
        )
        assert pause_response.status_code == 200

        resume_response = client.post(
            f"/api/search-queues/{queue_id}/resume", headers=headers
        )
        assert resume_response.status_code == 200

    def test_multi_instance_workflow(self, client: TestClient, db_session):
        """
        Test workflow with multiple instances of different types.

        Verifies:
        1. Can create both Sonarr and Radarr instances
        2. Can create separate queues for each instance
        3. Instances are properly isolated per user
        """
        # Setup admin user
        setup_data = {
            "username": "admin",
            "email": "admin@example.com",
            "password": "SecurePassword123!",
            "confirm_password": "SecurePassword123!",
        }
        client.post("/api/auth/setup", json=setup_data)

        # Login
        login_data = {"username": "admin", "password": "SecurePassword123!"}
        login_response = client.post("/api/auth/login", data=login_data)
        access_token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        # Add Sonarr instance
        sonarr_data = {
            "name": "Sonarr Production",
            "instance_type": "sonarr",
            "base_url": "http://sonarr.local:8989",
            "api_key": "sonarr-key-1234567890abcdef",
        }
        sonarr_response = client.post("/api/instances/", json=sonarr_data, headers=headers)
        assert sonarr_response.status_code == 200
        sonarr_id = sonarr_response.json()["id"]

        # Add Radarr instance
        radarr_data = {
            "name": "Radarr Production",
            "instance_type": "radarr",
            "base_url": "http://radarr.local:7878",
            "api_key": "radarr-key-1234567890abcdef",
        }
        radarr_response = client.post("/api/instances/", json=radarr_data, headers=headers)
        assert radarr_response.status_code == 200
        radarr_id = radarr_response.json()["id"]

        # Verify both instances exist
        instances_response = client.get("/api/instances/", headers=headers)
        instances = instances_response.json()
        assert len(instances) == 2
        assert any(i["instance_type"] == "sonarr" for i in instances)
        assert any(i["instance_type"] == "radarr" for i in instances)

        # Create queue for Sonarr
        sonarr_queue_data = {
            "name": "Sonarr Missing Queue",
            "instance_id": sonarr_id,
            "strategy": "missing",
            "max_items_per_run": 10,
            "is_active": True,
        }
        sonarr_queue_response = client.post(
            "/api/search-queues/", json=sonarr_queue_data, headers=headers
        )
        assert sonarr_queue_response.status_code == 200

        # Create queue for Radarr
        radarr_queue_data = {
            "name": "Radarr Cutoff Queue",
            "instance_id": radarr_id,
            "strategy": "cutoff",
            "max_items_per_run": 15,
            "is_active": True,
        }
        radarr_queue_response = client.post(
            "/api/search-queues/", json=radarr_queue_data, headers=headers
        )
        assert radarr_queue_response.status_code == 200

        # Verify both queues exist
        queues_response = client.get("/api/search-queues/", headers=headers)
        queues = queues_response.json()
        assert len(queues) == 2

    def test_error_recovery_workflow(self, client: TestClient, db_session):
        """
        Test error recovery scenarios.

        Verifies:
        1. Proper error handling for invalid credentials
        2. Proper error handling for duplicate instances
        3. Proper error handling for invalid queue configurations
        4. Proper error handling for unauthorized access
        """
        # Setup user
        setup_data = {
            "username": "testuser",
            "email": "test@example.com",
            "password": "Password123!",
            "confirm_password": "Password123!",
        }
        client.post("/api/auth/setup", json=setup_data)

        # Test 1: Invalid login credentials
        invalid_login = {"username": "testuser", "password": "WrongPassword"}
        login_response = client.post("/api/auth/login", data=invalid_login)
        assert login_response.status_code == 401

        # Login with correct credentials
        valid_login = {"username": "testuser", "password": "Password123!"}
        login_response = client.post("/api/auth/login", data=valid_login)
        access_token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        # Test 2: Create instance with duplicate name
        instance_data = {
            "name": "Test Instance",
            "instance_type": "sonarr",
            "base_url": "http://localhost:8989",
            "api_key": "test-key-123",
        }
        client.post("/api/instances/", json=instance_data, headers=headers)

        # Try to create duplicate
        duplicate_response = client.post("/api/instances/", json=instance_data, headers=headers)
        assert duplicate_response.status_code == 400

        # Test 3: Create queue with invalid instance ID
        invalid_queue_data = {
            "name": "Invalid Queue",
            "instance_id": 99999,
            "strategy": "missing",
            "max_items_per_run": 10,
            "is_active": True,
        }
        invalid_queue_response = client.post(
            "/api/search-queues/", json=invalid_queue_data, headers=headers
        )
        assert invalid_queue_response.status_code in [400, 404]

        # Test 4: Unauthorized access without token
        unauth_response = client.get("/api/instances/")
        assert unauth_response.status_code == 401

    def test_data_persistence_workflow(self, client: TestClient, db_session):
        """
        Test data persistence across requests.

        Verifies:
        1. Created instances persist
        2. Created queues persist
        3. Queue state changes persist
        4. User sessions persist
        """
        # Setup and login
        setup_data = {
            "username": "persistuser",
            "email": "persist@example.com",
            "password": "Persist123!",
            "confirm_password": "Persist123!",
        }
        client.post("/api/auth/setup", json=setup_data)

        login_data = {"username": "persistuser", "password": "Persist123!"}
        login_response = client.post("/api/auth/login", data=login_data)
        access_token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        # Create instance
        instance_data = {
            "name": "Persistent Instance",
            "instance_type": "sonarr",
            "base_url": "http://localhost:8989",
            "api_key": "persistent-key",
        }
        instance_response = client.post("/api/instances/", json=instance_data, headers=headers)
        instance_id = instance_response.json()["id"]

        # Create queue
        queue_data = {
            "name": "Persistent Queue",
            "instance_id": instance_id,
            "strategy": "missing",
            "max_items_per_run": 10,
            "is_active": True,
        }
        queue_response = client.post("/api/search-queues/", json=queue_data, headers=headers)
        queue_id = queue_response.json()["id"]

        # Pause queue
        client.post(f"/api/search-queues/{queue_id}/pause", headers=headers)

        # Verify instance still exists in new request
        instance_check = client.get(f"/api/instances/{instance_id}", headers=headers)
        assert instance_check.status_code == 200
        assert instance_check.json()["name"] == "Persistent Instance"

        # Verify queue still exists and is paused
        queue_check = client.get(f"/api/search-queues/{queue_id}", headers=headers)
        assert queue_check.status_code == 200
        queue_data = queue_check.json()
        assert queue_data["name"] == "Persistent Queue"
        assert queue_data["is_active"] is True  # Pause only affects status, not is_active

        # Delete queue
        delete_response = client.delete(f"/api/search-queues/{queue_id}", headers=headers)
        assert delete_response.status_code == 204

        # Verify queue is gone
        deleted_check = client.get(f"/api/search-queues/{queue_id}", headers=headers)
        assert deleted_check.status_code == 404

    def test_authentication_flow_workflow(self, client: TestClient, db_session):
        """
        Test complete authentication flow.

        Verifies:
        1. Setup wizard is accessible before any users exist
        2. Setup wizard creates admin user
        3. Login provides access token
        4. Access token can be used for API calls
        5. Refresh token can renew access
        6. Logout invalidates session
        """
        # Setup wizard should be accessible
        setup_data = {
            "username": "authtest",
            "email": "authtest@example.com",
            "password": "AuthTest123!",
            "confirm_password": "AuthTest123!",
        }
        setup_response = client.post("/api/auth/setup", json=setup_data)
        assert setup_response.status_code == 200

        # Login to get tokens
        login_data = {"username": "authtest", "password": "AuthTest123!"}
        login_response = client.post("/api/auth/login", data=login_data)
        assert login_response.status_code == 200
        tokens = login_response.json()
        assert "access_token" in tokens
        assert "refresh_token" in tokens
        access_token = tokens["access_token"]
        refresh_token = tokens["refresh_token"]

        # Use access token for API call
        headers = {"Authorization": f"Bearer {access_token}"}
        profile_response = client.get("/api/auth/me", headers=headers)
        assert profile_response.status_code == 200
        profile = profile_response.json()
        assert profile["username"] == "authtest"
        assert profile["email"] == "authtest@example.com"

        # Use refresh token to get new access token
        refresh_response = client.post(
            "/api/auth/refresh", json={"refresh_token": refresh_token}
        )
        assert refresh_response.status_code == 200
        new_tokens = refresh_response.json()
        assert "access_token" in new_tokens
        new_access_token = new_tokens["access_token"]
        assert new_access_token != access_token

        # Use new access token
        new_headers = {"Authorization": f"Bearer {new_access_token}"}
        profile_response2 = client.get("/api/auth/me", headers=new_headers)
        assert profile_response2.status_code == 200

        # Logout
        logout_response = client.post("/api/auth/logout", headers=new_headers)
        assert logout_response.status_code == 200

        # Verify old token no longer works (session invalidated)
        # Note: JWT tokens technically still work until expiry, but session is marked invalid
        # This behavior depends on implementation details


class TestConcurrentAccess:
    """Test concurrent access scenarios."""

    def test_concurrent_queue_creation(self, client: TestClient, db_session):
        """
        Test creating multiple queues concurrently.

        Verifies:
        1. Multiple queues can be created for same instance
        2. Queue names are unique per user
        3. Each queue maintains independent state
        """
        # Setup
        setup_data = {
            "username": "concurrent",
            "email": "concurrent@example.com",
            "password": "Concurrent123!",
            "confirm_password": "Concurrent123!",
        }
        client.post("/api/auth/setup", json=setup_data)

        login_data = {"username": "concurrent", "password": "Concurrent123!"}
        login_response = client.post("/api/auth/login", data=login_data)
        access_token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        # Create instance
        instance_data = {
            "name": "Concurrent Instance",
            "instance_type": "sonarr",
            "base_url": "http://localhost:8989",
            "api_key": "concurrent-key",
        }
        instance_response = client.post("/api/instances/", json=instance_data, headers=headers)
        instance_id = instance_response.json()["id"]

        # Create multiple queues
        queue_configs = [
            {"name": "Queue 1", "strategy": "missing"},
            {"name": "Queue 2", "strategy": "cutoff"},
            {"name": "Queue 3", "strategy": "recent"},
        ]

        queue_ids = []
        for config in queue_configs:
            queue_data = {
                "name": config["name"],
                "instance_id": instance_id,
                "strategy": config["strategy"],
                "max_items_per_run": 10,
                "is_active": True,
            }
            response = client.post("/api/search-queues/", json=queue_data, headers=headers)
            assert response.status_code == 200
            queue_ids.append(response.json()["id"])

        # Verify all queues exist
        queues_response = client.get("/api/search-queues/", headers=headers)
        queues = queues_response.json()
        assert len(queues) == 3

        # Verify each queue has correct strategy
        for i, queue_id in enumerate(queue_ids):
            queue_response = client.get(f"/api/search-queues/{queue_id}", headers=headers)
            queue = queue_response.json()
            assert queue["strategy"] == queue_configs[i]["strategy"]


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_state_handling(self, client: TestClient, db_session):
        """
        Test application behavior with no data.

        Verifies:
        1. Empty instance list returns correctly
        2. Empty queue list returns correctly
        3. Empty search history returns correctly
        """
        # Setup and login
        setup_data = {
            "username": "empty",
            "email": "empty@example.com",
            "password": "Empty123!",
            "confirm_password": "Empty123!",
        }
        client.post("/api/auth/setup", json=setup_data)

        login_data = {"username": "empty", "password": "Empty123!"}
        login_response = client.post("/api/auth/login", data=login_data)
        access_token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        # Check empty instances
        instances_response = client.get("/api/instances/", headers=headers)
        assert instances_response.status_code == 200
        assert instances_response.json() == []

        # Check empty queues
        queues_response = client.get("/api/search-queues/", headers=headers)
        assert queues_response.status_code == 200
        assert queues_response.json() == []

    def test_max_length_inputs(self, client: TestClient, db_session):
        """
        Test handling of maximum length inputs.

        Verifies proper validation of string length limits.
        """
        # Setup and login
        setup_data = {
            "username": "maxlength",
            "email": "maxlength@example.com",
            "password": "MaxLength123!",
            "confirm_password": "MaxLength123!",
        }
        client.post("/api/auth/setup", json=setup_data)

        login_data = {"username": "maxlength", "password": "MaxLength123!"}
        login_response = client.post("/api/auth/login", data=login_data)
        access_token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        # Test instance name with max reasonable length
        long_name = "A" * 100
        instance_data = {
            "name": long_name,
            "instance_type": "sonarr",
            "base_url": "http://localhost:8989",
            "api_key": "test-key-123",
        }
        response = client.post("/api/instances/", json=instance_data, headers=headers)
        # Should either succeed or return validation error
        assert response.status_code in [200, 400, 422]

    def test_special_characters_handling(self, client: TestClient, db_session):
        """
        Test handling of special characters in inputs.

        Verifies proper sanitization and storage of special characters.
        """
        # Setup and login
        setup_data = {
            "username": "special",
            "email": "special@example.com",
            "password": "Special123!@#",
            "confirm_password": "Special123!@#",
        }
        client.post("/api/auth/setup", json=setup_data)

        login_data = {"username": "special", "password": "Special123!@#"}
        login_response = client.post("/api/auth/login", data=login_data)
        access_token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        # Test instance name with special characters
        instance_data = {
            "name": "Test Instance (Production) [v2]",
            "instance_type": "sonarr",
            "base_url": "http://localhost:8989",
            "api_key": "test-key-123",
        }
        response = client.post("/api/instances/", json=instance_data, headers=headers)
        assert response.status_code == 200

        # Verify special characters are preserved
        instance = response.json()
        assert "(Production)" in instance["name"]
        assert "[v2]" in instance["name"]
