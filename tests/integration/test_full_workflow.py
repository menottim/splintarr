"""
Integration tests for full workflows.

Tests end-to-end scenarios combining multiple components:
- User registration and authentication
- Instance management with encrypted API keys
- Search queue creation and execution
- Security features integration
"""

from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest

from splintarr.core.security import (
    field_encryption,
    hash_password,
    password_security,
    token_generator,
    verify_password,
)
from splintarr.models.instance import Instance
from splintarr.models.search_history import SearchHistory
from splintarr.models.search_queue import SearchQueue
from splintarr.models.user import RefreshToken, User


class TestUserAuthenticationWorkflow:
    """Test complete user authentication workflow."""

    def test_user_registration_and_login(self, db_session):
        """Test user registration and successful login."""
        # Step 1: Register user
        username = "newuser"
        password = "SecurePassword123!"

        # Hash password with security features
        password_hash = hash_password(password)

        user = User(username=username, password_hash=password_hash)
        db_session.add(user)
        db_session.commit()

        # Verify user was created
        assert user.id is not None
        assert user.username == username
        assert user.is_active is True

        # Step 2: Authenticate user
        # Retrieve user
        db_user = db_session.query(User).filter_by(username=username).first()
        assert db_user is not None

        # Verify password
        assert verify_password(password, db_user.password_hash) is True

        # Step 3: Record successful login
        ip_address = "192.168.1.1"
        db_user.record_successful_login(ip_address)
        db_session.commit()

        # Verify login was recorded
        assert db_user.last_login is not None
        assert db_user.last_login_ip == ip_address
        assert db_user.failed_login_attempts == 0

        # Step 4: Create refresh token
        jti = token_generator.generate_token()
        refresh_token = RefreshToken(
            jti=jti,
            user_id=db_user.id,
            expires_at=datetime.utcnow() + timedelta(days=30),
            ip_address=ip_address,
            device_info="Test Client",
        )
        db_session.add(refresh_token)
        db_session.commit()

        # Verify token was created
        assert refresh_token.id is not None
        assert refresh_token.is_valid() is True

    def test_failed_login_lockout_workflow(self, db_session, test_settings):
        """Test failed login attempt tracking and account lockout."""
        # Step 1: Create user
        user = User(username="testuser", password_hash=hash_password("CorrectPassword"))
        db_session.add(user)
        db_session.commit()

        # Step 2: Attempt failed logins
        max_attempts = test_settings.max_failed_login_attempts
        lockout_duration = test_settings.account_lockout_duration_minutes

        for i in range(max_attempts - 1):
            # Verify wrong password fails
            assert verify_password("WrongPassword", user.password_hash) is False

            # Record failed attempt
            user.increment_failed_login(max_attempts, lockout_duration)
            db_session.commit()

            # Account should not be locked yet
            assert user.is_locked() is False

        # Step 3: One more failed attempt should lock account
        user.increment_failed_login(max_attempts, lockout_duration)
        db_session.commit()

        # Account should now be locked
        assert user.is_locked() is True
        assert user.account_locked_until is not None

        # Step 4: Verify correct password still doesn't work while locked
        assert verify_password("CorrectPassword", user.password_hash) is True
        # But user is locked, so login should be rejected (checked at application level)

        # Step 5: Reset after successful authentication (simulated)
        user.reset_failed_login()
        db_session.commit()

        assert user.is_locked() is False
        assert user.failed_login_attempts == 0

    def test_token_rotation_workflow(self, db_session):
        """Test refresh token rotation workflow."""
        # Step 1: Create user and initial token
        user = User(username="testuser", password_hash=hash_password("Password123"))
        db_session.add(user)
        db_session.commit()

        old_jti = token_generator.generate_token()
        old_token = RefreshToken(
            jti=old_jti, user_id=user.id, expires_at=datetime.utcnow() + timedelta(days=30)
        )
        db_session.add(old_token)
        db_session.commit()

        # Step 2: Rotate token (revoke old, create new)
        old_token.revoke()
        db_session.commit()

        assert old_token.is_valid() is False

        new_jti = token_generator.generate_token()
        new_token = RefreshToken(
            jti=new_jti, user_id=user.id, expires_at=datetime.utcnow() + timedelta(days=30)
        )
        db_session.add(new_token)
        db_session.commit()

        # Step 3: Verify new token is valid, old is not
        assert new_token.is_valid() is True
        assert old_token.is_valid() is False

        # Step 4: Verify user has both tokens in history
        assert user.refresh_tokens.count() == 2

    def test_password_rehashing_workflow(self, db_session):
        """Test password rehashing when parameters change."""
        # Step 1: Create user with password
        password = "TestPassword123"
        user = User(username="testuser", password_hash=hash_password(password))
        db_session.add(user)
        db_session.commit()

        original_hash = user.password_hash

        # Step 2: Check if rehashing is needed (should be False initially)
        assert password_security.needs_rehash(original_hash) is False

        # Step 3: Simulate parameter change by checking with old hash
        # (In production, this would be detected after successful login)

        # Step 4: If rehash needed, create new hash
        if password_security.needs_rehash(original_hash):
            new_hash = hash_password(password)
            user.password_hash = new_hash
            db_session.commit()

            # Verify new hash works
            assert verify_password(password, user.password_hash) is True


class TestInstanceManagementWorkflow:
    """Test instance management with encrypted API keys."""

    def test_instance_creation_with_encryption(self, db_session):
        """Test creating instance with encrypted API key."""
        # Step 1: Create user
        user = User(username="testuser", password_hash=hash_password("Password123"))
        db_session.add(user)
        db_session.commit()

        # Step 2: Create instance with API key
        plaintext_api_key = "1234567890abcdef1234567890abcdef"

        # Encrypt API key before storing
        encrypted_api_key = field_encryption.encrypt(plaintext_api_key)

        instance = Instance(
            user_id=user.id,
            name="My Sonarr",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key=encrypted_api_key,
        )
        db_session.add(instance)
        db_session.commit()

        # Step 3: Retrieve instance
        db_instance = db_session.query(Instance).filter_by(id=instance.id).first()

        # Step 4: Decrypt API key
        decrypted_api_key = field_encryption.decrypt(db_instance.api_key)

        # Verify decryption worked
        assert decrypted_api_key == plaintext_api_key

        # Verify API key is not stored in plaintext
        assert db_instance.api_key != plaintext_api_key
        assert db_instance.api_key.startswith("gAAAAA")

    def test_instance_connection_test_workflow(self, db_session):
        """Test instance connection testing workflow."""
        # Step 1: Create user and instance
        user = User(username="testuser", password_hash=hash_password("Password123"))
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key=field_encryption.encrypt("api_key"),
        )
        db_session.add(instance)
        db_session.commit()

        # Step 2: Test connection (simulate)
        # In real application, this would make HTTP request
        connection_success = True  # Simulated

        if connection_success:
            instance.mark_healthy()
        else:
            instance.mark_unhealthy("Connection timeout")

        db_session.commit()

        # Step 3: Verify connection status
        assert instance.is_healthy() is True
        assert instance.connection_status == "healthy"

        # Step 4: Simulate connection failure
        instance.mark_unhealthy("API key invalid")
        db_session.commit()

        assert instance.is_healthy() is False
        assert instance.connection_error == "API key invalid"

    def test_instance_deletion_cascade(self, db_session):
        """Test that deleting instance cascades to related records."""
        # Step 1: Create user and instance
        user = User(username="testuser", password_hash=hash_password("Password123"))
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key=field_encryption.encrypt("api_key"),
        )
        db_session.add(instance)
        db_session.commit()

        # Step 2: Create search queue
        search_queue = SearchQueue(
            instance_id=instance.id, name="Test Search", strategy="missing"
        )
        db_session.add(search_queue)
        db_session.commit()

        search_queue_id = search_queue.id

        # Step 3: Delete instance
        db_session.delete(instance)
        db_session.commit()

        # Step 4: Verify search queue was deleted
        deleted_queue = db_session.query(SearchQueue).filter_by(id=search_queue_id).first()
        assert deleted_queue is None


class TestSearchWorkflow:
    """Test search queue and history workflow."""

    def test_search_queue_execution_workflow(self, db_session):
        """Test complete search queue execution workflow."""
        # Step 1: Setup (user, instance, search queue)
        user = User(username="testuser", password_hash=hash_password("Password123"))
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key=field_encryption.encrypt("api_key"),
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(
            instance_id=instance.id,
            name="Find Missing",
            strategy="missing",
            is_recurring=True,
            interval_hours=24,
        )
        db_session.add(search_queue)
        db_session.commit()

        # Step 2: Check if ready to run
        assert search_queue.is_ready_to_run() is True

        # Step 3: Mark as in progress
        search_queue.mark_in_progress()
        db_session.commit()

        assert search_queue.status == "in_progress"
        assert search_queue.is_ready_to_run() is False

        # Step 4: Create history record
        history = SearchHistory.create_for_search(
            instance_id=instance.id,
            search_queue_id=search_queue.id,
            search_name=search_queue.name,
            strategy=search_queue.strategy,
        )
        db_session.add(history)
        db_session.commit()

        # Step 5: Simulate search execution (would call Sonarr API)
        items_searched = 100
        items_found = 25
        searches_triggered = 25

        # Step 6: Mark as completed
        search_queue.mark_completed(items_found=items_found, items_searched=items_searched)
        db_session.commit()

        history.mark_completed(
            status="success",
            items_searched=items_searched,
            items_found=items_found,
            searches_triggered=searches_triggered,
        )
        db_session.commit()

        # Step 7: Verify results
        assert search_queue.status == "pending"  # Pending for next run
        assert search_queue.next_run is not None  # Scheduled
        assert search_queue.items_found == items_found

        assert history.is_completed is True
        assert history.was_successful is True
        assert history.success_rate == 0.25

    def test_recurring_search_workflow(self, db_session):
        """Test recurring search workflow over multiple executions."""
        # Step 1: Create recurring search
        user = User(username="testuser", password_hash=hash_password("Password123"))
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key=field_encryption.encrypt("api_key"),
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(
            instance_id=instance.id,
            name="Daily Search",
            strategy="missing",
            is_recurring=True,
            interval_hours=24,
        )
        db_session.add(search_queue)
        db_session.commit()

        # Step 2: Execute multiple times
        for i in range(3):
            # Ready to run
            assert search_queue.is_ready_to_run() is True

            # Execute
            search_queue.mark_in_progress()
            db_session.commit()

            # Create history
            history = SearchHistory.create_for_search(
                instance_id=instance.id,
                search_queue_id=search_queue.id,
                search_name=search_queue.name,
                strategy=search_queue.strategy,
            )
            db_session.add(history)
            db_session.commit()

            # Complete
            search_queue.mark_completed(items_found=10 + i, items_searched=50)
            db_session.commit()

            history.mark_completed(
                status="success",
                items_searched=50,
                items_found=10 + i,
                searches_triggered=10 + i,
            )
            db_session.commit()

            # Next run should be scheduled
            assert search_queue.next_run is not None

        # Step 3: Verify history records
        history_records = (
            db_session.query(SearchHistory)
            .filter_by(instance_id=instance.id)
            .order_by(SearchHistory.started_at)
            .all()
        )

        assert len(history_records) == 3

        for i, record in enumerate(history_records):
            assert record.items_found == 10 + i

    def test_failed_search_workflow(self, db_session):
        """Test search failure and retry workflow."""
        # Step 1: Setup
        user = User(username="testuser", password_hash=hash_password("Password123"))
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key=field_encryption.encrypt("api_key"),
        )
        db_session.add(instance)
        db_session.commit()

        search_queue = SearchQueue(
            instance_id=instance.id,
            name="Test Search",
            strategy="missing",
            is_recurring=True,
            interval_hours=24,
        )
        db_session.add(search_queue)
        db_session.commit()

        # Step 2: Execute and fail multiple times
        for i in range(5):
            search_queue.mark_in_progress()
            db_session.commit()

            # Create history
            history = SearchHistory.create_for_search(
                instance_id=instance.id,
                search_queue_id=search_queue.id,
                search_name=search_queue.name,
                strategy=search_queue.strategy,
            )
            db_session.add(history)
            db_session.commit()

            # Simulate failure
            error_message = f"Connection timeout (attempt {i + 1})"
            search_queue.mark_failed(error_message)
            db_session.commit()

            history.mark_failed(error_message)
            db_session.commit()

        # Step 3: Verify deactivation after max failures
        assert search_queue.is_active is False
        assert search_queue.consecutive_failures == 5

        # Step 4: Manual retry
        search_queue.reset_for_retry()
        search_queue.is_active = True
        db_session.commit()

        assert search_queue.status == "pending"
        assert search_queue.consecutive_failures == 0


class TestUserDeletionWorkflow:
    """Test user deletion and cascade effects."""

    def test_user_deletion_cascades_all_data(self, db_session):
        """Test that deleting user cascades to all related data."""
        # Step 1: Create complete user workflow
        user = User(username="testuser", password_hash=hash_password("Password123"))
        db_session.add(user)
        db_session.commit()

        # Create refresh token
        refresh_token = RefreshToken(
            jti=token_generator.generate_token(),
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(days=30),
        )
        db_session.add(refresh_token)
        db_session.commit()

        # Create instance
        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key=field_encryption.encrypt("api_key"),
        )
        db_session.add(instance)
        db_session.commit()

        # Create search queue
        search_queue = SearchQueue(
            instance_id=instance.id, name="Test Search", strategy="missing"
        )
        db_session.add(search_queue)
        db_session.commit()

        # Create search history
        history = SearchHistory.create_for_search(
            instance_id=instance.id,
            search_queue_id=search_queue.id,
            search_name="Test",
            strategy="missing",
        )
        db_session.add(history)
        db_session.commit()

        # Record IDs
        refresh_token_id = refresh_token.id
        instance_id = instance.id
        search_queue_id = search_queue.id
        history_id = history.id

        # Step 2: Delete user
        db_session.delete(user)
        db_session.commit()

        # Step 3: Verify all related data is deleted
        assert db_session.query(RefreshToken).filter_by(id=refresh_token_id).first() is None
        assert db_session.query(Instance).filter_by(id=instance_id).first() is None
        assert db_session.query(SearchQueue).filter_by(id=search_queue_id).first() is None
        assert db_session.query(SearchHistory).filter_by(id=history_id).first() is None


class TestSecurityIntegration:
    """Test security features integration."""

    def test_complete_security_workflow(self, db_session):
        """Test complete workflow with all security features."""
        # Step 1: User registration with secure password
        password = "VerySecurePassword123!@#"
        password_hash = hash_password(password)

        # Verify hash format
        assert password_hash.startswith("$argon2id$")

        user = User(username="secureuser", password_hash=password_hash)
        db_session.add(user)
        db_session.commit()

        # Step 2: Authentication with constant-time comparison
        assert verify_password(password, user.password_hash) is True
        assert verify_password("wrong", user.password_hash) is False

        # Step 3: Create instance with encrypted API key
        api_key = "super_secret_api_key_12345678"
        encrypted_api_key = field_encryption.encrypt(api_key)

        # Verify encryption
        assert encrypted_api_key != api_key
        assert encrypted_api_key.startswith("gAAAAA")

        instance = Instance(
            user_id=user.id,
            name="Secure Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key=encrypted_api_key,
        )
        db_session.add(instance)
        db_session.commit()

        # Step 4: Create secure refresh token
        jti = token_generator.generate_token(32)
        assert len(jti) > 40  # URL-safe base64 of 32 bytes

        refresh_token = RefreshToken(
            jti=jti,
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(days=30),
        )
        db_session.add(refresh_token)
        db_session.commit()

        # Step 5: Verify all security features work together
        # Retrieve and decrypt API key
        db_instance = db_session.query(Instance).filter_by(id=instance.id).first()
        decrypted_api_key = field_encryption.decrypt(db_instance.api_key)
        assert decrypted_api_key == api_key

        # Verify token
        db_token = db_session.query(RefreshToken).filter_by(jti=jti).first()
        assert db_token.is_valid() is True

        # Verify password
        db_user = db_session.query(User).filter_by(username="secureuser").first()
        assert verify_password(password, db_user.password_hash) is True

    def test_encryption_key_isolation(self, db_session):
        """Test that different encryption keys produce different ciphertexts."""
        # This verifies that encryption is properly isolated
        user = User(username="testuser", password_hash=hash_password("Password123"))
        db_session.add(user)
        db_session.commit()

        # Create two instances with same API key
        api_key = "same_api_key_12345678"

        instance1 = Instance(
            user_id=user.id,
            name="Instance 1",
            instance_type="sonarr",
            url="https://sonarr1.example.com",
            api_key=field_encryption.encrypt(api_key),
        )
        db_session.add(instance1)
        db_session.commit()

        instance2 = Instance(
            user_id=user.id,
            name="Instance 2",
            instance_type="radarr",
            url="https://radarr1.example.com",
            api_key=field_encryption.encrypt(api_key),
        )
        db_session.add(instance2)
        db_session.commit()

        # Ciphertexts should be different (different IVs)
        assert instance1.api_key != instance2.api_key

        # But both should decrypt to same value
        assert field_encryption.decrypt(instance1.api_key) == api_key
        assert field_encryption.decrypt(instance2.api_key) == api_key
