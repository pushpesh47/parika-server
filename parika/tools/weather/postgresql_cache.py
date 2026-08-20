"""
PARIKA Weather API - Cache - PostgreSQL Implementation

PostgreSQL-backed TTL-based cache for normalized weather responses.
Prevents cache stampedes via per-key locks.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .cache import WeatherCache, WeatherCacheConfig, WeatherCacheError, make_cache_key


@dataclass(frozen=True, slots=True, kw_only=True)
class PostgreSQLWeatherCacheConfig:
    """Typed configuration for `PostgreSQLWeatherCache`."""

    enabled: bool = True
    ttl_seconds: float = 1200.0
    max_entries: int = 500


class PostgreSQLWeatherCache:
    """
    PostgreSQL-backed TTL-based cache for normalized weather responses.

    Uses both asyncio.Lock (for async contexts) and threading.Lock
    (for multi-threaded contexts) to prevent cache stampedes across
    all execution environments.
    """

    __slots__ = (
        "_pool",
        "_ttl_seconds",
        "_max_entries",
        "_memory",
        "_async_locks",
        "_thread_locks",
        "_locks_lock",
    )

    def __init__(
        self,
        pool,
        *,
        ttl_seconds: float = 1200.0,
        max_entries: int = 500,
    ) -> None:
        if not isinstance(pool, (str, Path, PurePath)):
            self._pool = pool
        else:
            raise TypeError("pool must be a psycopg_pool.ConnectionPool instance")

        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._memory: dict[str, tuple[float, dict[str, Any]]] = {}
        self._async_locks: dict[int, dict[str, asyncio.Lock]] = {}  # loop_id -> {key -> lock}
        self._thread_locks: dict[str, threading.Lock] = {}
        self._locks_lock = threading.Lock()

    def initialize(self) -> None:
        """No-op: schema is managed by Alembic migrations."""
        pass

    def shutdown(self) -> None:
        """No-op: pool is managed by PoolManager."""
        pass

    def _get_async_lock(self, key: str) -> asyncio.Lock:
        """Get or create a per-key asyncio lock for stampede prevention."""
        # Use the current running loop's ID to isolate locks per event loop
        try:
            loop = asyncio.get_running_loop()
            loop_id = id(loop)
        except RuntimeError:
            # No running loop - create a fallback lock
            loop_id = 0
        
        with self._locks_lock:
            if loop_id not in self._async_locks:
                self._async_locks[loop_id] = {}
            if key not in self._async_locks[loop_id]:
                self._async_locks[loop_id][key] = asyncio.Lock()
            return self._async_locks[loop_id][key]

    def _get_thread_lock(self, key: str) -> threading.Lock:
        """Get or create a per-key threading lock for stampede prevention."""
        with self._locks_lock:
            if key not in self._thread_locks:
                self._thread_locks[key] = threading.Lock()
            return self._thread_locks[key]

    async def get_or_fetch(
        self,
        key: str,
        fetch_func,
        *fetch_args,
        **fetch_kwargs,
    ) -> tuple[dict[str, Any], str]:
        """
        Get cached data or fetch fresh data with stampede prevention.

        Returns:
            Tuple of (response_data, cache_status) where cache_status
            is one of "fresh" or "fetched".
        """
        async_lock = self._get_async_lock(key)
        thread_lock = self._get_thread_lock(key)

        # Fast path: check memory cache without lock
        now = time.time()
        memory_entry = self._memory.get(key)
        if memory_entry is not None:
            cached_at, data = memory_entry
            if now - cached_at <= self._ttl_seconds:
                return data, "fresh"
            # Expired - will need to refresh

        # Slow path: acquire thread lock and check again (double-checked locking)
        with thread_lock:
            # Re-check memory cache after acquiring thread lock
            now = time.time()
            memory_entry = self._memory.get(key)
            if memory_entry is not None:
                cached_at, data = memory_entry
                if now - cached_at <= self._ttl_seconds:
                    return data, "fresh"
                # Still expired, but we hold the lock so we'll refresh

            # Check PostgreSQL cache
            try:
                with self._pool.connection() as conn:
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(
                            "SELECT response, cached_at FROM cache.weather WHERE cache_key = %s;",
                            (key,),
                        )
                        row = cur.fetchone()
            except psycopg.Error as ex:
                raise WeatherCacheError(
                    "Failed to read from weather cache."
                ) from ex

            if row is not None:
                cached_at = float(row["cached_at"])
                if now - cached_at <= self._ttl_seconds:
                    data = _deserialize(row["response"])
                    self._memory[key] = (cached_at, data)
                    return data, "fresh"
                # Expired in PostgreSQL too

        # Thread lock released here - now use async lock for the actual fetch
        # This allows other threads to proceed with their synchronous checks
        async with async_lock:
            # Triple-check inside async lock (another task might have fetched while we waited)
            now = time.time()
            memory_entry = self._memory.get(key)
            if memory_entry is not None:
                cached_at, data = memory_entry
                if now - cached_at <= self._ttl_seconds:
                    return data, "fresh"

            # Another check: maybe another task already wrote to PostgreSQL
            try:
                with self._pool.connection() as conn:
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(
                            "SELECT response, cached_at FROM cache.weather WHERE cache_key = %s;",
                            (key,),
                        )
                        row = cur.fetchone()
            except psycopg.Error as ex:
                raise WeatherCacheError(
                    "Failed to read from weather cache."
                ) from ex
            if row is not None:
                cached_at = float(row["cached_at"])
                if now - cached_at <= self._ttl_seconds:
                    data = _deserialize(row["response"])
                    self._memory[key] = (cached_at, data)
                    return data, "fresh"

            # Only ONE task reaches here - fetch fresh data
            data = await fetch_func(*fetch_args, **fetch_kwargs)

            # Store in cache
            self.set(key, data)

            return data, "fetched"

    def set(self, key: str, data: dict[str, Any]) -> None:
        """Store `data` under `key`, evicting the oldest entry if full."""
        now = time.time()
        self._memory[key] = (now, data)

        if len(self._memory) > self._max_entries:
            oldest_key = min(self._memory, key=lambda k: self._memory[k][0])
            del self._memory[oldest_key]

        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO cache.weather (cache_key, response, cached_at) "
                        "VALUES (%s, %s, %s) "
                        "ON CONFLICT (cache_key) DO UPDATE SET response = EXCLUDED.response, cached_at = EXCLUDED.cached_at;",
                        (key, _serialize(data), now),
                    )
                    cur.execute(
                        """
                        DELETE FROM cache.weather WHERE cache_key NOT IN (
                            SELECT cache_key FROM cache.weather
                            ORDER BY cached_at DESC LIMIT %s
                        );
                        """,
                        (self._max_entries,),
                    )
                    conn.commit()

        except psycopg.Error as ex:
            raise WeatherCacheError(
                "Failed to write to weather cache."
            ) from ex

    async def aset(self, key: str, data: dict[str, Any]) -> None:
        """Async version of set for use in get_or_fetch."""
        self.set(key, data)

    def get_cached(self, key: str) -> tuple[dict[str, Any], float] | None:
        """
        Get cached data without fetching. Returns (data, cached_at) or None.

        Used for stale-cache fallback scenarios. Returns None if expired.
        """
        now = time.time()

        memory_entry = self._memory.get(key)
        if memory_entry is not None:
            cached_at, data = memory_entry
            if now - cached_at <= self._ttl_seconds:
                return data, cached_at
            # Expired in memory
            del self._memory[key]

        try:
            with self._pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        "SELECT response, cached_at FROM cache.weather WHERE cache_key = %s;",
                        (key,),
                    )
                    row = cur.fetchone()
        except psycopg.Error as ex:
            raise WeatherCacheError(
                "Failed to read from weather cache."
            ) from ex

        if row is None:
            return None

        cached_at = float(row["cached_at"])
        if now - cached_at > self._ttl_seconds:
            # Expired in PostgreSQL
            self._delete(key)
            return None

        data = _deserialize(row["response"])
        self._memory[key] = (cached_at, data)
        return data, cached_at

    def _delete(self, key: str) -> None:
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM cache.weather WHERE cache_key = %s;", (key,)
                    )
                    conn.commit()
        except psycopg.Error:
            pass


def _serialize(data: dict[str, Any]) -> str:
    return json.dumps(data, separators=(",", ":"))


def _deserialize(payload) -> dict[str, Any]:
    if isinstance(payload, str):
        return json.loads(payload)
    return payload