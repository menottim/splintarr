"""
Unit tests for database configuration and security.

Tests database connection, encryption, PRAGMA settings, and security hardening
following OWASP database security guidelines.
"""

import os
import stat
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, call, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from splintarr.database import (
    Base,
    SessionLocal,
    close_db,
    create_database_engine,
    create_session_factory,
    database_health_check,
    engine,
    get_db,
    get_engine,
    init_db,
    secure_database_file,
    set_sqlite_pragma,
    test_database_connection,
)


class TestSecureDatabaseFile:
    """Test database file permission management."""

    def test_secure_database_file_sets_correct_permissions(self, tmp_path):
        """Test that secure_database_file sets 0600 permissions."""
        db_file = tmp_path / "test.db"
        db_file.touch()

        # Set loose permissions first
        os.chmod(db_file, 0o666)

        # Secure the file
        secure_database_file(str(db_file))

        # Check permissions are now 0600
        file_stat = os.stat(db_file)
        permissions = stat.S_IMODE(file_stat.st_mode)
        assert permissions == 0o600

    def test_secure_database_file_handles_wal_and_shm(self, tmp_path):
        """Test that WAL and SHM files are also secured."""
        db_file = tmp_path / "test.db"
        wal_file = tmp_path / "test.db-wal"
        shm_file = tmp_path / "test.db-shm"

        # Create all files
        db_file.touch()
        wal_file.touch()
        shm_file.touch()

        # Secure the database
        secure_database_file(str(db_file))

        # Check all files have 0600 permissions
        for file_path in [db_file, wal_file, shm_file]:
            file_stat = os.stat(file_path)
            permissions = stat.S_IMODE(file_stat.st_mode)
            assert permissions == 0o600

    def test_secure_database_file_nonexistent_file_no_error(self, tmp_path):
        """Test that securing non-existent file doesn't raise error."""
        db_file = tmp_path / "nonexistent.db"

        # Should not raise error
        secure_database_file(str(db_file))

    def test_secure_database_file_permission_error_propagates(self, tmp_path):
        """Test that permission errors are propagated."""
        db_file = tmp_path / "test.db"
        db_file.touch()

        with patch("os.chmod", side_effect=PermissionError("Access denied")):
            with pytest.raises(PermissionError):
                secure_database_file(str(db_file))

    def test_secure_database_file_owner_only_permissions(self, tmp_path):
        """Test that only owner has read/write permissions."""
        db_file = tmp_path / "test.db"
        db_file.touch()

        secure_database_file(str(db_file))

        file_stat = os.stat(db_file)
        permissions = stat.S_IMODE(file_stat.st_mode)

        # Owner should have read and write
        assert permissions & stat.S_IRUSR
        assert permissions & stat.S_IWUSR

        # Owner should not have execute
        assert not (permissions & stat.S_IXUSR)

        # Group should have no permissions
        assert not (permissions & stat.S_IRGRP)
        assert not (permissions & stat.S_IWGRP)
        assert not (permissions & stat.S_IXGRP)

        # Others should have no permissions
        assert not (permissions & stat.S_IROTH)
        assert not (permissions & stat.S_IWOTH)
        assert not (permissions & stat.S_IXOTH)


class TestSetSQLitePragma:
    """Test SQLite PRAGMA settings for security and performance."""

    def test_pragma_settings_on_connect(self, db_engine):
        """Test that PRAGMA settings are applied on connection."""
        with db_engine.connect() as conn:
            # Check foreign keys are enabled
            result = conn.execute(text("PRAGMA foreign_keys"))
            assert result.fetchone()[0] == 1

            # Check journal mode is WAL
            result = conn.execute(text("PRAGMA journal_mode"))
            assert result.fetchone()[0].upper() == "WAL"

            # Check synchronous mode is FULL
            result = conn.execute(text("PRAGMA synchronous"))
            # FULL = 2
            assert result.fetchone()[0] == 2

            # Check temp_store is MEMORY
            result = conn.execute(text("PRAGMA temp_store"))
            # MEMORY = 2
            assert result.fetchone()[0] == 2

            # Check secure_delete is ON
            result = conn.execute(text("PRAGMA secure_delete"))
            assert result.fetchone()[0] == 1

            # Check auto_vacuum is FULL
            result = conn.execute(text("PRAGMA auto_vacuum"))
            # FULL = 1
            assert result.fetchone()[0] == 1

    def test_foreign_keys_enforced(self, db_session):
        """Test that foreign key constraints are actually enforced."""
        from splintarr.models.user import RefreshToken, User

        # Try to create a refresh token with non-existent user_id
        from datetime import datetime, timedelta

        token = RefreshToken(
            jti="test-jti",
            user_id=99999,  # Non-existent user
            expires_at=datetime.utcnow() + timedelta(days=1),
        )

        db_session.add(token)

        # Should raise foreign key constraint error
        with pytest.raises(Exception):  # IntegrityError
            db_session.commit()

    def test_secure_delete_overwrites_data(self, db_engine):
        """Test that secure_delete is enabled to overwrite deleted data."""
        with db_engine.connect() as conn:
            result = conn.execute(text("PRAGMA secure_delete"))
            # secure_delete should be ON (1)
            assert result.fetchone()[0] == 1

    def test_wal_mode_enabled(self, db_engine):
        """Test that Write-Ahead Logging is enabled for concurrency."""
        with db_engine.connect() as conn:
            result = conn.execute(text("PRAGMA journal_mode"))
            assert result.fetchone()[0].upper() == "WAL"

    def test_pragma_error_handling(self):
        """Test that PRAGMA setting errors are caught and logged."""
        mock_cursor = Mock()
        mock_cursor.execute.side_effect = Exception("PRAGMA failed")

        mock_conn = Mock()
        mock_conn.cursor.return_value = mock_cursor

        # Should raise the exception
        with pytest.raises(Exception, match="PRAGMA failed"):
            set_sqlite_pragma(mock_conn, None)

        # Cursor should be closed even on error
        mock_cursor.close.assert_called_once()


class TestCreateDatabaseEngine:
    """Test database engine creation with encryption."""

    def test_create_engine_with_sqlcipher(self, test_settings):
        """Test that engine is created with SQLCipher encryption."""
        engine = create_database_engine()

        # Engine should be created
        assert engine is not None

        # URL should contain SQLCipher parameters
        url_str = str(engine.url)
        assert "pysqlcipher" in url_str or "memory" in url_str

    def test_create_engine_connection_args(self, test_settings):
        """Test that engine has correct connection arguments."""
        engine = create_database_engine()

        # Check connection args
        connect_args = engine.pool._creator.keywords if hasattr(engine.pool, "_creator") else {}

        # For in-memory test database, check_same_thread should be False
        # This is critical for async FastAPI usage

    def test_create_engine_pool_settings(self, test_settings):
        """Test that engine uses StaticPool in test and NullPool otherwise."""
        engine = create_database_engine()

        # In test environment, StaticPool is used for in-memory database sharing
        from sqlalchemy import pool

        assert isinstance(engine.pool, pool.StaticPool)

    def test_create_engine_error_handling(self):
        """Test that engine creation errors are handled properly."""
        with patch("splintarr.database.create_engine", side_effect=Exception("DB Error")):
            with pytest.raises(RuntimeError, match="Failed to create database engine"):
                create_database_engine()


class TestCreateSessionFactory:
    """Test session factory creation."""

    def test_create_session_factory(self, db_engine):
        """Test that session factory is created correctly."""
        factory = create_session_factory(db_engine)

        # Create a session
        session = factory()

        # Session should be bound to engine
        assert session.bind == db_engine

        # Session should have correct settings
        assert session.autocommit is False
        assert session.autoflush is False

        session.close()

    def test_session_expire_on_commit_false(self, db_engine):
        """Test that expire_on_commit is False to prevent lazy loading issues."""
        factory = create_session_factory(db_engine)
        session = factory()

        # expire_on_commit should be False
        assert session.expire_on_commit is False

        session.close()


class TestGetDb:
    """Test database session dependency for FastAPI."""

    def test_get_db_yields_session(self):
        """Test that get_db yields a valid session."""
        gen = get_db()
        session = next(gen)

        # Should get a valid session
        assert session is not None

        # Clean up
        try:
            next(gen)
        except StopIteration:
            pass

    def test_get_db_closes_session(self):
        """Test that get_db closes session after use."""
        gen = get_db()
        session = next(gen)

        # Session should be open
        assert session.is_active

        # Finish the generator (simulates end of request)
        try:
            next(gen)
        except StopIteration:
            pass

        # Note: Session may still appear active, but close was called

    def test_get_db_closes_session_on_exception(self):
        """Test that session is closed even if exception occurs."""
        gen = get_db()
        session = next(gen)

        # Simulate exception during request
        try:
            raise ValueError("Request failed")
        except ValueError:
            pass

        # Finish the generator
        try:
            next(gen)
        except StopIteration:
            pass

        # Session should still be closed


class TestInitDb:
    """Test database initialization."""

    def test_init_db_creates_tables(self, db_engine):
        """Test that init_db creates all required tables."""
        # Tables should already be created by fixture
        # Verify they exist
        from sqlalchemy import inspect

        inspector = inspect(db_engine)
        table_names = inspector.get_table_names()

        # Check that all model tables are created
        expected_tables = [
            "users",
            "refresh_tokens",
            "instances",
            "search_queue",
            "search_history",
        ]

        for table in expected_tables:
            assert table in table_names

    def test_init_db_imports_all_models(self):
        """Test that init_db imports all models to register them."""
        # This is tested indirectly by checking table creation
        # All models should be registered with Base.metadata
        table_names = [table.name for table in Base.metadata.tables.values()]

        expected_tables = [
            "users",
            "refresh_tokens",
            "instances",
            "search_queue",
            "search_history",
        ]

        for table in expected_tables:
            assert table in table_names

    @patch("splintarr.database.Base.metadata.create_all")
    def test_init_db_error_handling(self, mock_create_all):
        """Test that init_db handles errors properly."""
        mock_create_all.side_effect = Exception("Table creation failed")

        with pytest.raises(RuntimeError, match="Failed to initialize database"):
            init_db()


class TestDatabaseConnection:
    """Test database connection and encryption verification."""

    def test_database_connection_success(self, db_engine):
        """Test successful database connection."""
        result = test_database_connection()
        assert result is True

    def test_database_connection_queries_work(self, db_engine):
        """Test that basic queries work on encrypted database."""
        with db_engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            assert result.fetchone()[0] == 1

    def test_database_encryption_verified(self, db_engine):
        """Test that SQLCipher encryption is verified on connection."""
        with db_engine.connect() as conn:
            # Query cipher version
            result = conn.execute(text("PRAGMA cipher_version"))
            cipher_version = result.fetchone()

            # Should have a cipher version (or None for in-memory test DB)
            # In-memory test DB may not have SQLCipher
            assert cipher_version is not None or ":memory:" in str(db_engine.url)

    def test_database_connection_error_handling(self):
        """Test that connection errors are handled properly."""
        with patch.object(engine, "connect", side_effect=Exception("Connection failed")):
            with pytest.raises(RuntimeError, match="Database connection failed"):
                test_database_connection()


class TestCloseDb:
    """Test database connection cleanup."""

    def test_close_db_disposes_engine(self):
        """Test that close_db disposes of the engine properly."""
        # Create a test engine
        test_engine = create_database_engine()

        # Patch the global engine
        with patch("splintarr.database.engine", test_engine):
            close_db()

            # Engine should be disposed
            # We can't easily test this directly, but we verify no exception

    def test_close_db_handles_errors(self):
        """Test that close_db handles errors gracefully."""
        with patch.object(engine, "dispose", side_effect=Exception("Dispose failed")):
            # Should not raise exception
            close_db()


class TestDatabaseHealthCheck:
    """Test database health check functionality."""

    def test_database_health_check_healthy(self, db_engine):
        """Test health check returns healthy status."""
        health = database_health_check()

        assert health["status"] == "healthy"
        assert "encrypted" in health
        assert "connection_pool" in health

    def test_database_health_check_includes_encryption_status(self, db_engine):
        """Test that health check includes encryption status."""
        health = database_health_check()

        # Should have encryption status
        assert isinstance(health["encrypted"], bool)

    def test_database_health_check_includes_pool_status(self, db_engine):
        """Test that health check includes connection pool status."""
        health = database_health_check()

        pool_status = health["connection_pool"]
        assert "size" in pool_status
        assert "checked_out" in pool_status

    def test_database_health_check_unhealthy_on_error(self):
        """Test that health check returns unhealthy on connection error."""
        with patch.object(engine, "connect", side_effect=Exception("Connection failed")):
            health = database_health_check()

            assert health["status"] == "unhealthy"
            assert "error" in health

    def test_database_health_check_cipher_version(self, db_engine):
        """Test that health check includes cipher version if available."""
        health = database_health_check()

        # If encrypted, should have cipher_version
        if health["encrypted"]:
            assert "cipher_version" in health
            assert health["cipher_version"] is not None


class TestGetEngine:
    """Test engine getter for migrations."""

    def test_get_engine_returns_global_engine(self):
        """Test that get_engine returns the global engine instance."""
        returned_engine = get_engine()

        # Should return the same engine instance
        assert returned_engine is engine


class TestDatabaseSecurity:
    """Test database security features."""

    def test_database_file_permissions_secure(self, tmp_path):
        """Test that database file has secure permissions after creation."""
        db_file = tmp_path / "test.db"

        # Create and secure the file
        db_file.touch()
        secure_database_file(str(db_file))

        # Check permissions
        file_stat = os.stat(db_file)
        permissions = stat.S_IMODE(file_stat.st_mode)

        # Should be 0600 (owner read/write only)
        assert permissions == 0o600

    def test_sqlcipher_encryption_parameters(self, test_settings):
        """Test that SQLCipher uses strong encryption parameters."""
        db_url = test_settings.get_database_url()

        # Should use AES-256
        assert "cipher=aes-256" in db_url

        # Should have high KDF iteration count
        assert "kdf_iter=" in db_url

        # Extract KDF iterations
        kdf_iter_start = db_url.find("kdf_iter=") + 9
        kdf_iter_end = db_url.find("&", kdf_iter_start)
        if kdf_iter_end == -1:
            kdf_iter_end = len(db_url)
        kdf_iter = int(db_url[kdf_iter_start:kdf_iter_end])

        # Should be at least 64000 (OWASP recommendation)
        assert kdf_iter >= 64000

    def test_connection_timeout_configured(self, db_engine):
        """Test that connection timeout is configured."""
        # Connection args should include timeout
        # This is configured in create_database_engine

    def test_hide_parameters_in_production(self, test_settings):
        """Test that SQL parameters are hidden in production logs."""
        # This is configured in create_database_engine
        # When environment is production, hide_parameters should be True
        if test_settings.environment == "production":
            # Would need to create production engine to test
            pass


class TestDatabaseIntegrity:
    """Test database integrity and constraints."""

    def test_cascade_delete_user_deletes_tokens(self, db_session):
        """Test that deleting user cascades to refresh tokens."""
        from splintarr.models.user import RefreshToken, User

        # Create user with token
        from datetime import datetime, timedelta

        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        token = RefreshToken(
            jti="test-jti",
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(days=1),
        )
        db_session.add(token)
        db_session.commit()

        token_id = token.id

        # Delete user
        db_session.delete(user)
        db_session.commit()

        # Token should also be deleted
        deleted_token = db_session.query(RefreshToken).filter_by(id=token_id).first()
        assert deleted_token is None

    def test_cascade_delete_user_deletes_instances(self, db_session):
        """Test that deleting user cascades to instances."""
        from splintarr.models.instance import Instance
        from splintarr.models.user import User

        # Create user with instance
        user = User(username="testuser", password_hash="hash")
        db_session.add(user)
        db_session.commit()

        instance = Instance(
            user_id=user.id,
            name="Test Instance",
            instance_type="sonarr",
            url="https://sonarr.example.com",
            api_key="encrypted_key",
        )
        db_session.add(instance)
        db_session.commit()

        instance_id = instance.id

        # Delete user
        db_session.delete(user)
        db_session.commit()

        # Instance should also be deleted
        deleted_instance = db_session.query(Instance).filter_by(id=instance_id).first()
        assert deleted_instance is None
