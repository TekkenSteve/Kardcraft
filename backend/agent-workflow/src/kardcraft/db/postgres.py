"""
PostgreSQL async database client for Kardcraft.
"""

import os
import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool, AsyncAdaptedQueuePool
from sqlalchemy import text
from ..utils.logger import logger
from .models import Base


class PostgresClient:
    """Async PostgreSQL client with connection pooling."""

    def __init__(self):
        self._engine = None
        self._session_factory = None
        self._initialized = False

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
        """Initialize the database connection pool."""
        if self._initialized:
            return

        config = self._get_config()
        logger.info(
            f"Initializing PostgreSQL at {config['host']}:{config['port']}/{config['db']}"
        )

        self._engine = create_async_engine(
            config["url"],
            echo=False,
            poolclass=AsyncAdaptedQueuePool,
            pool_size=20,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=3600,
        )

        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        self._initialized = True
        logger.info("PostgreSQL initialized successfully")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a database session. Use as context manager."""
        if not self._initialized:
            await self.initialize()

        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def create_tables(self):
        """Create all tables if they don't exist."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created")

    async def drop_tables(self):
        """Drop all tables (for testing)."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        logger.warning("Database tables dropped")

    async def close(self):
        """Close the connection pool."""
        if self._engine:
            await self._engine.dispose()
            self._initialized = False
            logger.info("PostgreSQL connection closed")

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
