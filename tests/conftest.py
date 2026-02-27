"""Pytest configuration and fixtures."""

import sys
from pathlib import Path as _Path

# Ensure the worktree's src directory is on sys.path so we test
# the local code rather than any editable-installed copy.
_worktree_src = str(_Path(__file__).resolve().parent.parent / "src")
if _worktree_src not in sys.path:
    sys.path.insert(0, _worktree_src)

import os
import secrets
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Set test environment variables BEFORE importing any application code
os.environ["ENVIRONMENT"] = "test"
os.environ["LOG_LEVEL"] = "DEBUG"
os.environ["SECRET_KEY"] = secrets.token_urlsafe(64)
os.environ["PEPPER"] = secrets.token_urlsafe(32)
os.environ["DATABASE_KEY"] = secrets.token_urlsafe(32)
os.environ["DATABASE_URL"] = "sqlite+pysqlcipher:///:memory:@/:memory:?cipher=aes-256-cfb&kdf_iter=64000"
os.environ["ALLOW_LOCAL_INSTANCES"] = "true"
os.environ["SECURE_COOKIES"] = "false"

from splintarr.config import Settings, settings
from splintarr.database import Base


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Create test settings with secure defaults."""
    # Generate temporary secrets for testing
    import secrets

    return Settings(
        environment="test",
        log_level="DEBUG",
        secret_key=secrets.token_urlsafe(64),
        pepper=secrets.token_urlsafe(32),
        database_key=secrets.token_urlsafe(32),
        database_url="sqlite+pysqlcipher:///:memory:@/:memory:?cipher=aes-256-cfb&kdf_iter=64000",
        allow_local_instances=True,
        secure_cookies=False,  # Disable for testing
    )


@pytest.fixture(scope="function")
def db_engine(test_settings):
    """Create a test database engine with SQLCipher."""
    # Use in-memory database for tests
    encryption_key = test_settings.get_database_key()
    engine = create_engine(
        f"sqlite+pysqlcipher://:{encryption_key}@/:memory:?cipher=aes-256-cfb&kdf_iter=64000",
        connect_args={"check_same_thread": False},
        echo=False,
    )

    # Create tables
    Base.metadata.create_all(bind=engine)

    yield engine

    # Cleanup
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine) -> Generator[Session, None, None]:
    """Create a test database session."""
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = TestingSessionLocal()

    yield session

    session.close()


@pytest.fixture
def temp_secrets_dir():
    """Create temporary directory for secret files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        secrets_dir = Path(tmpdir) / "secrets"
        secrets_dir.mkdir()
        yield secrets_dir


@pytest.fixture(scope="function")
def client(db_session, test_settings) -> Generator[TestClient, None, None]:
    """Create a FastAPI test client with test database."""
    from splintarr.database import get_db

    # Override get_db dependency to use test database session
    def override_get_db():
        try:
            yield db_session
        finally:
            pass  # Don't close, fixture handles it

    # Mock init_db to prevent production database access during tests
    # Tables are already created by db_engine fixture
    def mock_init_db():
        pass

    # Patch settings, init_db, and test_database_connection.
    # We patch both splintarr.database (canonical location) and splintarr.main
    # (where the lifespan context manager references them via module-level imports).
    with patch("splintarr.config.settings", test_settings), \
         patch("splintarr.database.init_db", mock_init_db), \
         patch("splintarr.database.test_database_connection", lambda: True), \
         patch("splintarr.main.init_db", mock_init_db), \
         patch("splintarr.main.test_database_connection", lambda: True):

        # Import app AFTER patching
        from splintarr.main import app

        app.dependency_overrides[get_db] = override_get_db

        with TestClient(app) as test_client:
            yield test_client

        # Clean up
        app.dependency_overrides.clear()
