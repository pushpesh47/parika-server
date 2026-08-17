"""
PARIKA Weather API - Cache

Caches normalized weather responses keyed by normalized coordinates
with a configurable TTL. Uses SQLite for cross-run persistence plus
an in-process dict for same-run hits without a database round trip.

Prevents cache stampedes via per-key locks (asyncio.Lock for async
contexts, threading.Lock for multi-threaded contexts) so concurrent
requests after expiry trigger only one provider fetch.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any

SQLITE_BUSY_TIMEOUT_MS: int = 5000


class WeatherCacheError(Exception):
    """Raised when the weather cache fails to read or write."""


@dataclass(frozen=True, slots=True, kw_only=True)
class WeatherCacheConfig:
    """Typed configuration for `WeatherCache`."""

    enabled: bool = True
    ttl_seconds: float = 1200.0
    max_entries: int = 500


def make_cache_key(latitude: float, longitude: float) -> str:
    """
    Build a normalized cache key from coordinates.

    Normalizes to 4 decimal places (~11m precision) to avoid
    fragmentation from tiny floating-point differences while still
    distinguishing different locations.
    """
    norm_lat = round(latitude, 4)
    norm_lon = round(longitude, 4)
    return f"{norm_lat}:{norm_lon}"


class WeatherCache:
    """
    TTL-based cache for normalized weather responses.

    When `database_path` is `None`, operates purely in-process (no
    cross-run persistence) -- useful for tests.

    Uses both asyncio.Lock (for async contexts) and threading.Lock
    (for multi-threaded contexts) to prevent cache stampedes across
    all execution environments.
    """

    __slots__ = (
        "_database_path",
        "_connection",
        "_ttl_seconds",
        "_max_entries",
        "_memory",
        "_async_locks",
        "_thread_locks",
        "_locks_lock",  # Protects the lock dictionaries
        "_sqlite_lock",  # Global lock for SQLite operations
    )

    def __init__(
        self,
        database_path: Path | None,
        *,
        ttl_seconds: float = 1200.0,
        max_entries: int = 500,
    ) -> None:
        if database_path is not None and not isinstance(database_path, PurePath):
            raise TypeError("database_path must be a pathlib.Path object or None.")

        self._database_path = database_path
        self._connection: sqlite3.Connection | None = None
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._memory: dict[str, tuple[float, dict[str, Any]]] = {}
        self._async_locks: dict[str, asyncio.Lock] = {}
        self._thread_locks: dict[str, threading.Lock] = {}
        self._locks_lock = threading.Lock()
        self._sqlite_lock = threading.Lock()

    def initialize(self) -> None:
        if self._database_path is None or self._connection is not None:
            return

        try:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)

            self._connection = sqlite3.connect(database=self._database_path, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row

            self._connection.execute("PRAGMA journal_mode = WAL;")
            self._connection.execute("PRAGMA synchronous = NORMAL;")
            self._connection.execute(
                f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS};"
            )
            with self._sqlite_lock:
                self._connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS weather_cache (
                        cache_key TEXT PRIMARY KEY,
                        response TEXT NOT NULL,
                        cached_at REAL NOT NULL
                    );
                    """
                )
                self._connection.commit()

        except Exception:
            if self._connection is not None:
                try:
                    self._connection.close()
                finally:
                    self._connection = None
            raise

    def shutdown(self) -> None:
        if self._connection is None:
            return

        try:
            self._connection.close()
        except sqlite3.Error as ex:
            raise WeatherCacheError(
                "Failed to shut down weather cache."
            ) from ex
        finally:
            self._connection = None

    def _get_async_lock(self, key: str) -> asyncio.Lock:
        """Get or create a per-key asyncio lock for stampede prevention."""
        with self._locks_lock:
            if key not in self._async_locks:
                self._async_locks[key] = asyncio.Lock()
            return self._async_locks[key]

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

            # Check SQLite cache (with global SQLite lock)
            if self._connection is not None:
                with self._sqlite_lock:
                    try:
                        row = self._connection.execute(
                            "SELECT response, cached_at FROM weather_cache WHERE cache_key = ?;",
                            (key,),
                        ).fetchone()

                    except sqlite3.Error as ex:
                        raise WeatherCacheError(
                            "Failed to read from weather cache."
                        ) from ex

                if row is not None:
                    cached_at = float(row["cached_at"])
                    if now - cached_at <= self._ttl_seconds:
                        data = _deserialize(row["response"])
                        self._memory[key] = (cached_at, data)
                        return data, "fresh"
                    # Expired in SQLite too

            # Cache miss or expired - fetch fresh data
            # Use async lock for the actual fetch (allows other async tasks to proceed)
            async with async_lock:
                # Triple-check inside async lock (another task might have fetched while we waited)
                now = time.time()
                memory_entry = self._memory.get(key)
                if memory_entry is not None:
                    cached_at, data = memory_entry
                    if now - cached_at <= self._ttl_seconds:
                        return data, "fresh"

                # Another check: maybe another task already wrote to SQLite
                if self._connection is not None:
                    with self._sqlite_lock:
                        try:
                            row = self._connection.execute(
                                "SELECT response, cached_at FROM weather_cache WHERE cache_key = ?;",
                                (key,),
                            ).fetchone()
                        except sqlite3.Error as ex:
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

        if self._connection is None:
            return

        with self._sqlite_lock:
            try:
                self._connection.execute(
                    "INSERT OR REPLACE INTO weather_cache (cache_key, response, cached_at) "
                    "VALUES (?, ?, ?);",
                    (key, _serialize(data), now),
                )
                self._connection.execute(
                    """
                    DELETE FROM weather_cache WHERE cache_key NOT IN (
                        SELECT cache_key FROM weather_cache
                        ORDER BY cached_at DESC LIMIT ?
                    );
                    """,
                    (self._max_entries,),
                )
                self._connection.commit()

            except sqlite3.Error as ex:
                self._connection.rollback()
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

        if self._connection is None:
            return None

        with self._sqlite_lock:
            try:
                row = self._connection.execute(
                    "SELECT response, cached_at FROM weather_cache WHERE cache_key = ?;",
                    (key,),
                ).fetchone()

            except sqlite3.Error as ex:
                raise WeatherCacheError(
                    "Failed to read from weather cache."
                ) from ex

            if row is None:
                return None

            cached_at = float(row["cached_at"])
            if now - cached_at > self._ttl_seconds:
                # Expired in SQLite
                self._delete(key)
                return None

            data = _deserialize(row["response"])
            self._memory[key] = (cached_at, data)
            return data, cached_at

    def _delete(self, key: str) -> None:
        if self._connection is None:
            return

        with self._sqlite_lock:
            try:
                self._connection.execute(
                    "DELETE FROM weather_cache WHERE cache_key = ?;", (key,)
                )
                self._connection.commit()
            except sqlite3.Error:
                self._connection.rollback()


def _serialize(data: dict[str, Any]) -> str:
    return json.dumps(data, separators=(",", ":"))


def _deserialize(payload: str) -> dict[str, Any]:
    return json.loads(payload)