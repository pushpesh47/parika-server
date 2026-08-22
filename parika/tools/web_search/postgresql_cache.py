"""
PARIKA Web Search Tool - Result Cache - PostgreSQL Implementation

PostgreSQL-backed TTL-based cache for ranked (pre-page-fetch) SearchResult pools.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path, PurePath
from types import MappingProxyType

import psycopg
from psycopg.rows import dict_row

from .cache import SearchResultCache, SearchResultCacheConfig, SearchResultCacheError, make_cache_key
from .search_result import SearchResult


@dataclass(frozen=True, slots=True, kw_only=True)
class PostgreSQLSearchResultCacheConfig:
    """Typed configuration for `PostgreSQLSearchResultCache`."""

    enabled: bool = True
    ttl_seconds: float = 900.0
    max_entries: int = 500


class PostgreSQLSearchResultCache:
    """
    PostgreSQL-backed TTL-based cache for ranked (pre-page-fetch) SearchResult pools.

    Thread-safe: uses connection pool, no single-thread affinity.
    """

    __slots__ = ("_pool", "_ttl_seconds", "_max_entries", "_memory")

    def __init__(
        self,
        pool,
        *,
        ttl_seconds: float = 900.0,
        max_entries: int = 500,
    ) -> None:
        if not isinstance(pool, (str, Path, PurePath)):
            self._pool = pool
        else:
            raise TypeError("pool must be a psycopg_pool.ConnectionPool instance")

        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._memory: dict[str, tuple[float, tuple[SearchResult, ...]]] = {}

    def initialize(self) -> None:
        """No-op: schema is managed by Alembic migrations."""
        pass

    def shutdown(self) -> None:
        """No-op: pool is managed by PoolManager."""
        pass

    def get(self, key: str) -> tuple[SearchResult, ...] | None:
        """Return cached results for `key`, or None if absent/expired."""

        now = time.time()

        memory_entry = self._memory.get(key)

        if memory_entry is not None:
            cached_at, results = memory_entry

            if now - cached_at <= self._ttl_seconds:
                return results

            del self._memory[key]

        try:
            with self._pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        "SELECT results, cached_at FROM cache.web_search WHERE cache_key = %s;",
                        (key,),
                    )
                    row = cur.fetchone()

            if row is None:
                return None

            if now - float(row["cached_at"]) > self._ttl_seconds:
                self._delete(key)
                return None

            results = _deserialize(row["results"])
            self._memory[key] = (float(row["cached_at"]), results)

            return results

        except psycopg.Error as ex:
            raise SearchResultCacheError(
                "Failed to read from search result cache."
            ) from ex

    def set(self, key: str, results: tuple[SearchResult, ...]) -> None:
        """Store `results` under `key`, evicting the oldest entry if full."""

        now = time.time()
        self._memory[key] = (now, results)

        if len(self._memory) > self._max_entries:
            oldest_key = min(self._memory, key=lambda k: self._memory[k][0])
            del self._memory[oldest_key]

        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO cache.web_search (cache_key, results, cached_at) "
                        "VALUES (%s, %s, %s) "
                        "ON CONFLICT (cache_key) DO UPDATE SET results = EXCLUDED.results, cached_at = EXCLUDED.cached_at;",
                        (key, _serialize(results), now),
                    )
                    cur.execute(
                        """
                        DELETE FROM cache.web_search WHERE cache_key NOT IN (
                            SELECT cache_key FROM cache.web_search
                            ORDER BY cached_at DESC LIMIT %s
                        );
                        """,
                        (self._max_entries,),
                    )
                    conn.commit()

        except psycopg.Error as ex:
            raise SearchResultCacheError(
                "Failed to write to search result cache."
            ) from ex

    def _delete(self, key: str) -> None:
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM cache.web_search WHERE cache_key = %s;", (key,)
                    )
                    conn.commit()
        except psycopg.Error:
            pass


def _serialize(results: tuple[SearchResult, ...]) -> str:
    return json.dumps(
        [
            {
                "title": r.title,
                "url": r.url,
                "snippet": r.snippet,
                "display_url": r.display_url,
            }
            for r in results
        ]
    )


def _deserialize(payload: str | list) -> tuple[SearchResult, ...]:
    if isinstance(payload, str):
        payload = json.loads(payload)
    return tuple(
        SearchResult(
            title=item["title"], url=item["url"],
            snippet=item.get("snippet"), display_url=item.get("display_url"),
        )
        for item in payload
    )