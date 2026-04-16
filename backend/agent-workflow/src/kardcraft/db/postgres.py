"""
PostgreSQL async database client for Kardcraft.
"""

import os
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import AsyncAdaptedQueuePool
from sqlalchemy import text
from ..utils.logger import logger
from .models import Base


@dataclass
class _LoopResources:
    loop_id: int
    engine: object
    session_factory: object


class PostgresClient:
    """Async PostgreSQL client with per-event-loop connection pools."""

    def __init__(self):
        self._resources_by_loop: dict[int, _LoopResources] = {}
        self._init_lock: asyncio.Lock | None = None

    def _get_config(self) -> dict:
        """Get PostgreSQL configuration from environment."""
        host = os.getenv("POSTGRES_HOST", "localhost")
        port = int(os.getenv("POSTGRES_PORT", "5432"))
        db = os.getenv("POSTGRES_DB", "kardcraft")
        user = os.getenv("POSTGRES_USER", "postgres")
        password = os.getenv("POSTGRES_PASSWORD", "postgres")

        # Use asyncpg driver
        return {
            "url": f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}",
            "host": host,
            "port": port,
            "db": db,
            "user": user,
        }

    async def initialize(self):
        """Initialize resources for the current event loop."""
        await self._get_loop_resources()

    async def _get_loop_resources(self) -> _LoopResources:
        loop = asyncio.get_running_loop()
        loop_id = id(loop)
        resources = self._resources_by_loop.get(loop_id)
        if resources is not None:
            return resources

        if self._init_lock is None:
            self._init_lock = asyncio.Lock()

        async with self._init_lock:
            resources = self._resources_by_loop.get(loop_id)
            if resources is not None:
                return resources
            resources = self._create_loop_resources(loop_id=loop_id)
            self._resources_by_loop[loop_id] = resources
            return resources

    def _create_loop_resources(self, *, loop_id: int) -> _LoopResources:
        config = self._get_config()
        logger.info(
            f"Initializing PostgreSQL at {config['host']}:{config['port']}/{config['db']} for loop={loop_id}"
        )

        engine = create_async_engine(
            config["url"],
            echo=False,
            poolclass=AsyncAdaptedQueuePool,
            pool_size=20,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=3600,
        )

        session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        logger.info(f"PostgreSQL initialized successfully for loop={loop_id}")
        return _LoopResources(
            loop_id=loop_id,
            engine=engine,
            session_factory=session_factory,
        )


    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a database session. Use as context manager."""
        resources = await self._get_loop_resources()

        async with resources.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def create_tables(self):
        """Create all tables if they don't exist."""
        resources = await self._get_loop_resources()
        async with resources.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created")

    async def drop_tables(self):
        """Drop all tables (for testing)."""
        resources = await self._get_loop_resources()
        async with resources.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        logger.warning("Database tables dropped")

    async def close(self):
        """Close loop-local connection pool; drop stale loop references safely."""
        current_loop_id = id(asyncio.get_running_loop())
        resources = self._resources_by_loop.pop(current_loop_id, None)
        if resources is not None:
            try:
                await resources.engine.dispose()
            except Exception as e:
                logger.warning(
                    f"Error disposing PostgreSQL engine for loop={current_loop_id}: {e}"
                )

        stale_loop_ids = [loop_id for loop_id in self._resources_by_loop]
        if stale_loop_ids:
            # Avoid cross-loop disposal; just drop references to prevent accidental reuse.
            logger.warning(
                "Dropping PostgreSQL loop resources without disposal for closed/foreign loops: "
                + ",".join(str(loop_id) for loop_id in stale_loop_ids)
            )
            for loop_id in stale_loop_ids:
                self._resources_by_loop.pop(loop_id, None)

        logger.info("PostgreSQL connection resources closed")

    async def verify_connection(self) -> bool:
        """Verify database connectivity."""
        try:
            async with self.session() as session:
                await session.execute(text("SELECT 1"))
            logger.info("PostgreSQL connection verified")
            return True
        except Exception as e:
            logger.error(f"PostgreSQL connection failed: {e}")
            return False


# Global instance
postgres = PostgresClient()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting DB session."""
    async with postgres.session() as session:
        yield session


__all__ = ["postgres", "PostgresClient", "get_session"]
