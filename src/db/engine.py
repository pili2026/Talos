"""SQLite async engine configuration with optimized PRAGMA settings."""

import logging
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from model.snapshot_model import Base

logger = logging.getLogger(__name__)


def create_snapshot_engine(db_path: str, echo: bool = False) -> AsyncEngine:
    """
    Create an async SQLite engine with optimized settings.

    Args:
        db_path: Path to the SQLite database file
        echo: Whether to echo SQL statements (for debugging)

    Returns:
        Configured AsyncEngine instance
    """
    # Ensure parent directory exists
    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    # Create async engine for SQLite
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=echo,
        # Connection pool settings for SQLite
        pool_pre_ping=True,  # Verify connections before using
        pool_recycle=3600,  # Recycle connections after 1 hour
    )

    # Configure PRAGMA settings for performance
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        """Set SQLite PRAGMA settings on connection."""
        cursor = dbapi_conn.cursor()
        # Enable WAL mode for better concurrency
        cursor.execute("PRAGMA journal_mode=WAL")
        # Use NORMAL synchronous mode (faster, still safe)
        cursor.execute("PRAGMA synchronous=NORMAL")
        # Set cache size to 64MB
        cursor.execute("PRAGMA cache_size=-64000")
        # Enable foreign keys
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
        logger.debug("SQLite PRAGMA settings applied")

    logger.info(f"Created async SQLite engine: {db_path}")
    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    """
    Create an async session factory.

    Args:
        engine: AsyncEngine instance

    Returns:
        Configured async_sessionmaker
    """
    return async_sessionmaker(
        engine,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )


async def init_database(engine: AsyncEngine) -> None:
    """
    Initialize database schema.

    Creates all tables if they don't exist.

    Args:
        engine: AsyncEngine instance
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database schema initialized")


async def get_db_file_size(db_path: str) -> int:
    """
    Get database file size in bytes.

    Args:
        db_path: Path to the SQLite database file

    Returns:
        File size in bytes, or 0 if file doesn't exist
    """
    db_file = Path(db_path)
    if db_file.exists():
        return db_file.stat().st_size
    return 0
