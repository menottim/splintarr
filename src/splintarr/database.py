"""
Database configuration and session management with SQLCipher encryption.

This module provides:
- SQLCipher encrypted database connection
- SQLAlchemy session management
- Database security hardening via PRAGMA settings
- Connection pooling configuration
- File permission management
"""

import os
import stat
from collections.abc import Generator
from typing import Any

import structlog
from sqlalchemy import create_engine, event, pool, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from splintarr.config import settings

logger = structlog.get_logger()

# SQLAlchemy Base for models
Base = declarative_base()


def secure_database_file(db_path: str) -> None:
    """
    Set restrictive file permissions on database files.

    Sets permissions to 0600 (rw-------) for:
    - Main database file
    - WAL (Write-Ahead Log) file
    - SHM (Shared Memory) file

    Args:
        db_path: Path to the database file
    """
    if not os.path.exists(db_path):
        logger.info("database_file_not_found", path=db_path)
        return

    try:
        # Set main database file to 0600 (owner read/write only)
        os.chmod(db_path, stat.S_IRUSR | stat.S_IWUSR)
        logger.info("database_file_secured", path=db_path, permissions="0600")

        # Also secure WAL and SHM files if they exist
        for suffix in ["-wal", "-shm"]:
            aux_path = db_path + suffix
            if os.path.exists(aux_path):
                os.chmod(aux_path, stat.S_IRUSR | stat.S_IWUSR)
                logger.debug("database_aux_file_secured", path=aux_path, permissions="0600")

    except Exception as e:
        logger.error("failed_to_secure_database_file", path=db_path, error=str(e))
        raise


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_conn: Any, connection_record: Any) -> None:
    """
    Set SQLite PRAGMA settings for security and performance.

    Note: Encryption PRAGMA (key, cipher, kdf_iter) are set in the connection
    creator function before this event fires.

    This event handler configures:
    - Foreign key constraints
    - Write-Ahead Logging (WAL) for better concurrency
    - Full synchronous mode for crash safety
    - Memory-based temp storage
    - Secure deletion (overwrite deleted data)
    - Automatic vacuum (skipped for in-memory databases)

    Args:
        dbapi_conn: DBAPI connection object
        connection_record: SQLAlchemy connection record
    """
    cursor = dbapi_conn.cursor()

    try:
        # Wait up to 5 seconds for database locks to clear
        cursor.execute("PRAGMA busy_timeout = 5000")

        # Enable foreign key constraints (referential integrity)
        cursor.execute("PRAGMA foreign_keys = ON")

        # Use Write-Ahead Logging for better concurrency
        cursor.execute("PRAGMA journal_mode = WAL")

        # Full synchronous mode for crash safety
        # FULL = sync after every transaction (safest)
        cursor.execute("PRAGMA synchronous = FULL")

        # Store temporary tables and indices in memory
        cursor.execute("PRAGMA temp_store = MEMORY")

        # Overwrite deleted data instead of just marking it as free
        # This prevents recovery of deleted sensitive data
        cursor.execute("PRAGMA secure_delete = ON")

        # Automatically reclaim free space
        # Note: Skip for in-memory databases as auto_vacuum breaks SQLCipher :memory: databases
        result = cursor.execute("PRAGMA database_list").fetchall()
        is_memory = any(row[2] in (":memory:", "") for row in result)

        if not is_memory:
            cursor.execute("PRAGMA auto_vacuum = FULL")

        logger.debug("sqlite_pragma_set", connection_id=id(dbapi_conn))

    except Exception as e:
        logger.error("failed_to_set_sqlite_pragma", error=str(e))
        raise
    finally:
        cursor.close()


def create_database_engine() -> Engine:
    """
    Create and configure the SQLAlchemy database engine with SQLCipher encryption.

    Uses a custom connection creator to ensure PRAGMA key is set immediately
    after connection, before SQLAlchemy tries to use the connection.

    Returns:
        Engine: Configured SQLAlchemy engine

    Raises:
        RuntimeError: If database configuration is invalid
    """
    try:
        from urllib.parse import urlparse

        import sqlcipher3

        database_url = settings.get_database_url()

        # Extract the database path from the URL
        parsed = urlparse(database_url)
        db_path = parsed.path

        # Get encryption settings
        db_key = settings.get_database_key()
        cipher = settings.database_cipher
        kdf_iter = settings.database_kdf_iter

        def creator():
            """
            Custom connection creator that sets up SQLCipher before returning connection.

            This is necessary because SQLCipher requires PRAGMA key to be set BEFORE
            any database operations, including creating the database file.
            """
            # Create connection using sqlcipher3 directly
            conn = sqlcipher3.connect(
                db_path,
                check_same_thread=False,
                timeout=30,
            )

            # CRITICAL: Set encryption key IMMEDIATELY after connection
            cursor = conn.cursor()
            try:
                # SQLCipher PRAGMA does not support parameterized queries.
                # Escape single quotes to prevent SQL syntax errors (MED-01).
                safe_key = db_key.replace("'", "''")
                safe_cipher = cipher.replace("'", "''")
                cursor.execute(f"PRAGMA key = '{safe_key}'")
                cursor.execute(f"PRAGMA cipher = '{safe_cipher}'")
                cursor.execute(f"PRAGMA kdf_iter = {kdf_iter}")
                cursor.execute("PRAGMA busy_timeout = 5000")
                logger.debug("sqlcipher_pragmas_set", db_path=db_path)
            finally:
                cursor.close()

            return conn

        # Create engine with custom creator
        # NullPool: SQLCipher requires a fresh connection per operation for thread safety.
        # StaticPool is used in tests for in-memory database sharing.
        # pool_pre_ping and pool_recycle are not applicable with NullPool.
        engine = create_engine(
            database_url,
            creator=creator,
            poolclass=pool.StaticPool if settings.environment == "test" else pool.NullPool,
            echo=settings.log_level == "DEBUG",
            echo_pool=settings.log_level == "DEBUG",
            hide_parameters=settings.environment == "production",
        )

        logger.info(
            "database_engine_created",
            environment=settings.environment,
            echo=settings.log_level == "DEBUG",
        )

        return engine

    except Exception as e:
        logger.error("failed_to_create_database_engine", error=str(e))
        raise RuntimeError(f"Failed to create database engine: {e}") from e


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """
    Create a session factory for database operations.

    Args:
        engine: SQLAlchemy engine

    Returns:
        sessionmaker: Session factory
    """
    return sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,  # Prevent lazy loading issues
    )


# Global engine and session factory (lazy initialization)
_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """
    Get or create the database engine instance.

    Returns:
        Engine: SQLAlchemy engine

    Note:
        Uses lazy initialization - engine is created on first access.
        This allows tests to import the module without triggering engine creation.
    """
    global _engine
    if _engine is None:
        _engine = create_database_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """
    Get or create the session factory.

    Returns:
        sessionmaker: Session factory

    Note:
        Uses lazy initialization - created on first access.
    """
    global _session_factory
    if _session_factory is None:
        _session_factory = create_session_factory(get_engine())
    return _session_factory


# Module-level exports for backwards compatibility
# These are lazily initialized when accessed
def __getattr__(name: str) -> Any:
    """
    Lazy attribute access for backwards compatibility.

    Allows `from database import engine, SessionLocal` to work
    while still using lazy initialization.
    """
    if name == "engine":
        return get_engine()
    elif name == "SessionLocal":
        return get_session_factory()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def get_db() -> Generator[Session]:
    """
    Dependency function for FastAPI to get database session.

    Yields:
        Session: SQLAlchemy database session

    Example:
        @app.get("/users")
        def get_users(db: Session = Depends(get_db)):
            return db.query(User).all()
    """
    session_factory = get_session_factory()
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """
    Initialize the database.

    Creates all tables defined in models and secures the database file.
    This should be called on application startup.

    Raises:
        RuntimeError: If database initialization fails
    """
    try:
        # Import all models to ensure they're registered with Base
        from splintarr.models import (  # noqa: F401
            Instance,
            LibraryEpisode,
            LibraryItem,
            NotificationConfig,
            RefreshToken,
            SearchExclusion,
            SearchHistory,
            SearchQueue,
            User,
        )

        # Create all tables
        engine = get_engine()
        Base.metadata.create_all(bind=engine)
        logger.info("database_tables_created")

        # Secure database file permissions
        database_url = settings.database_url
        if "sqlite:///" in database_url:
            db_path = database_url.replace("sqlite:///", "")
            if db_path.startswith("./"):
                db_path = os.path.abspath(db_path)
            secure_database_file(db_path)

        logger.info("database_initialized")

    except Exception as e:
        logger.error("failed_to_initialize_database", error=str(e))
        raise RuntimeError(f"Failed to initialize database: {e}") from e


def test_database_connection() -> bool:
    """
    Test database connection and encryption.

    Returns:
        bool: True if connection is successful

    Raises:
        RuntimeError: If connection fails
    """
    try:
        engine = get_engine()
        with engine.connect() as conn:
            # Test basic query
            result = conn.execute(text("SELECT 1"))
            result.fetchone()

            # Verify encryption is enabled (SQLCipher)
            result = conn.execute(text("PRAGMA cipher_version"))
            cipher_version = result.fetchone()

            if cipher_version:
                logger.info("database_connection_successful", cipher_version=cipher_version[0])
            else:
                logger.warning("database_encryption_not_verified")

            return True

    except Exception as e:
        logger.error("database_connection_failed", error=str(e))
        raise RuntimeError(f"Database connection failed: {e}") from e


def close_db() -> None:
    """
    Close database connections and dispose of the engine.

    This should be called on application shutdown.
    """
    global _engine
    try:
        if _engine is not None:
            _engine.dispose()
            logger.info("database_connections_closed")
    except Exception as e:
        logger.error("failed_to_close_database", error=str(e))


# Database health check
def database_health_check() -> dict[str, Any]:
    """
    Perform a database health check.

    Returns:
        dict: Health check status and details

    Example response:
        {
            "status": "healthy",
            "encrypted": True,
            "connection_pool": {
                "size": 5,
                "checked_out": 2
            }
        }
    """
    try:
        engine = get_engine()
        # Test connection
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

            # Check encryption
            result = conn.execute(text("PRAGMA cipher_version"))
            cipher_version = result.fetchone()

        # Get pool status (if available - NullPool doesn't have size/checkedout methods)
        pool_status = {}
        if hasattr(engine.pool, "size") and callable(engine.pool.size):
            pool_status["size"] = engine.pool.size()
        if hasattr(engine.pool, "checkedout") and callable(engine.pool.checkedout):
            pool_status["checked_out"] = engine.pool.checkedout()
        if not pool_status:
            pool_status["type"] = type(engine.pool).__name__

        return {
            "status": "healthy",
            "encrypted": cipher_version is not None,
            "cipher_version": cipher_version[0] if cipher_version else None,
            "connection_pool": pool_status,
        }

    except Exception as e:
        logger.error("database_health_check_failed", error=str(e))
        return {
            "status": "unhealthy",
            "error": str(e),
        }
