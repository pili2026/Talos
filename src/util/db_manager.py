import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from repository.model.snapshot_model import Base

logger = logging.getLogger("SQLiteSnapshotDBManager")


class SQLiteSnapshotDBManager:
    """
    Unified class to manage SQLite snapshot storage, matching the TimescaleDB DBManager style.
    """

    def __init__(self, db_path: str, echo: bool = False):
        self.db_path = db_path
        self.echo = echo

        # Ensure path exists
        db_file = Path(db_path)
        try:
            db_file.parent.mkdir(parents=True, exist_ok=True)
            logger.info(f"[SQLite] Data directory ready: {db_file.parent}")
        except PermissionError as e:
            logger.error(f"[SQLite] Cannot create directory {db_file.parent}: {e}")
            raise

        # ---- Sync engine (rarely used but kept for parity with DBManager) ----
        self.sync_engine = create_engine(f"sqlite:///{db_path}")

        # ---- Async engine ----
        self.async_engine: AsyncEngine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            echo=echo,
            pool_pre_ping=True,
            pool_recycle=3600,
        )

        # Apply PRAGMA on connection
        @event.listens_for(self.async_engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_conn, _):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=-64000")  # 64MB
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
            logger.debug("[SQLite] PRAGMA settings applied")

        # ---- Session factory ----
        self._session_factory = async_sessionmaker(
            self.async_engine,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )

        logger.info(f"[SQLite] Snapshot engine initialized at {db_path}")

    # ----------------------------------------------------------------------
    # Session APIs (same interface as DBManager)
    # ----------------------------------------------------------------------
    async def get_new_async_session(self) -> AsyncSession:
        return self._session_factory()

    @asynccontextmanager
    async def get_async_session(self) -> AsyncGenerator[AsyncSession, None]:
        async with self._session_factory() as session:
            yield session

    # ----------------------------------------------------------------------
    # Database initialization
    # ----------------------------------------------------------------------
    async def init_database(self) -> None:
        """Create all tables if not exist."""
        async with self.async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("[SQLite] Schema initialized")

    # ----------------------------------------------------------------------
    # Utility
    # ----------------------------------------------------------------------
    async def wait_for_db_available(self):
        """
        Loop until SQLite file can be connected.
        (SQLite always available unless path invalid.)
        """
        attempts = 0
        while True:
            try:
                async with self.async_engine.connect():
                    logger.info("[SQLite] Database is available!")
                    break
            except Exception as e:
                attempts += 1
                logger.warning(f"[SQLite] DB connect fail (attempt {attempts}), retrying... {e}")
                await asyncio.sleep(1)

    def get_file_size(self) -> int:
        """Return SQLite file size in bytes."""
        p = Path(self.db_path)
        return p.stat().st_size if p.exists() else 0

    # ----------------------------------------------------------------------
    # Cleanup / shutdown
    # ----------------------------------------------------------------------
    async def close_engine(self):
        logger.info("[SQLite] Closing async engine")
        await self.async_engine.dispose()
        logger.info("[SQLite] Closed successfully")
