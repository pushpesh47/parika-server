"""
PARIKA Database Connection Pool Management

Provides synchronous and asynchronous connection pools for PostgreSQL
using psycopg3's built-in pooling.
"""

from __future__ import annotations

import atexit
import threading
from contextlib import contextmanager
from typing import Generator, Optional

import psycopg
from psycopg_pool import ConnectionPool, AsyncConnectionPool

from .config import DatabaseConfig


class PoolManager:
    """
    Manages PostgreSQL connection pools for PARIKA.

    Provides both synchronous and asynchronous pools, with proper
    lifecycle management (initialization, shutdown).
    """

    _sync_pool: Optional[ConnectionPool] = None
    _async_pool: Optional[AsyncConnectionPool] = None
    _lock = threading.Lock()
    _initialized = False

    @classmethod
    def initialize_sync_pool(cls, config: DatabaseConfig) -> ConnectionPool:
        """
        Initialize the synchronous connection pool.

        Must be called from the thread that will own the pool
        (typically the Core worker thread).
        """
        with cls._lock:
            if cls._sync_pool is not None:
                return cls._sync_pool

            cls._sync_pool = ConnectionPool(
                config.to_dsn(),
                min_size=1,  # Reduced for tests
                max_size=config.pool_max_size,
                timeout=config.connect_timeout,
                kwargs={"autocommit": False},
                open=True,
            )
            cls._initialized = True
            return cls._sync_pool

    @classmethod
    async def initialize_async_pool(cls, config: DatabaseConfig) -> AsyncConnectionPool:
        """
        Initialize the asynchronous connection pool.

        Must be called from the async event loop (typically FastAPI lifespan).
        """
        with cls._lock:
            if cls._async_pool is not None:
                return cls._async_pool

            cls._async_pool = AsyncConnectionPool(
                config.to_async_dsn(),
                min_size=1,  # Reduced for tests
                max_size=config.pool_max_size,
                timeout=config.connect_timeout,
                kwargs={"autocommit": False},
                open=False,
            )
            await cls._async_pool.open()
            return cls._async_pool

    @classmethod
    def get_sync_pool(cls) -> ConnectionPool:
        """Get the synchronous connection pool."""
        if cls._sync_pool is None:
            raise RuntimeError("Synchronous pool not initialized. Call initialize_sync_pool() first.")
        return cls._sync_pool

    @classmethod
    def get_async_pool(cls) -> AsyncConnectionPool:
        """Get the asynchronous connection pool."""
        if cls._async_pool is None:
            raise RuntimeError("Asynchronous pool not initialized. Call initialize_async_pool() first.")
        return cls._async_pool

    @classmethod
    def shutdown_sync_pool(cls) -> None:
        """Shutdown the synchronous connection pool."""
        with cls._lock:
            if cls._sync_pool is not None:
                cls._sync_pool.close()
                cls._sync_pool = None

    @classmethod
    async def shutdown_async_pool(cls) -> None:
        """Shutdown the asynchronous connection pool."""
        with cls._lock:
            if cls._async_pool is not None:
                try:
                    await cls._async_pool.close()
                except Exception:
                    # Ignore errors during shutdown (e.g., loop already closed)
                    pass
                cls._async_pool = None

    @classmethod
    def shutdown_all(cls) -> None:
        """Shutdown both pools."""
        cls.shutdown_sync_pool()
        # Async pool shutdown must be awaited; call separately in async context

    @classmethod
    @contextmanager
    def connection(cls) -> Generator[psycopg.Connection, None, None]:
        """
        Context manager for acquiring a synchronous connection from the pool.

        Usage:
            with PoolManager.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
        """
        pool = cls.get_sync_pool()
        with pool.connection() as conn:
            yield conn

    @classmethod
    @contextmanager
    def transaction(cls) -> Generator[psycopg.Connection, None, None]:
        """
        Context manager for a synchronous transaction.

        Commits on success, rolls back on exception.
        """
        pool = cls.get_sync_pool()
        with pool.connection() as conn:
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    @classmethod
    async def aconnection(cls):
        """
        Async context manager for acquiring an async connection from the pool.

        Usage:
            async with PoolManager.aconnection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1")
        """
        pool = cls.get_async_pool()
        async with pool.connection() as conn:
            yield conn

    @classmethod
    async def atransaction(cls):
        """
        Async context manager for an async transaction.
        """
        pool = cls.get_async_pool()
        async with pool.connection() as conn:
            try:
                yield conn
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise


# Register cleanup on process exit
def _cleanup_pools() -> None:
    PoolManager.shutdown_sync_pool()


atexit.register(_cleanup_pools)