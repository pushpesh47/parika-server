"""
PARIKA Web Search Tool - Result Cache

Caches the ranked (pre-page-fetch) candidate pool produced by
`WebSearchToolDriver._run_search_pipeline()`, keyed by a normalized
query and the backend's identity, with a TTL. This is the one real
gap identified in Advanced Search Improvements -- ranking, dedup,
validation, and query normalization already existed; only caching was
missing (see
docs/architecture/Intelligence_Foundation_Design.md section 10).

Backed by SQLite for cross-run persistence (consistent with PARIKA's
"Do NOT replace SQLite" constraint) plus an in-process dict for
same-run hits without a database round trip. Never caches page
content: only the pre-enrichment SearchResult pool, exactly what
`_run_search_pipeline()` produces.
"""

from __future__ import annotations

import json
import sqlite3
import time

from dataclasses import dataclass
from pathlib import Path, PurePath

from .search_result import SearchResult

SQLITE_BUSY_TIMEOUT_MS: int = 5000


class SearchResultCacheError(Exception):
    """Raised when the search result cache fails to read or write."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchResultCacheConfig:
    """Typed configuration for `SearchResultCache`."""

    enabled: bool = True
    ttl_seconds: float = 900.0
    max_entries: int = 500


def make_cache_key(query: str, backend_name: str) -> str:
    """
    Build a normalized cache key from a query and backend identity.

    Uses simple case/whitespace normalization -- deliberately not a
    full re-run of `QueryNormalizer` (which rewrites *search intent*,
    not just formatting) to keep the cache key computation trivial and
    dependency-free.
    """

    normalized_query = " ".join(query.strip().lower().split())

    return f"{backend_name}:{normalized_query}"


class SearchResultCache:
    """
    TTL-based cache for ranked (pre-page-fetch) SearchResult pools.

    When `database_path` is `None`, operates purely in-process (no
    cross-run persistence) -- useful for tests and for callers that
    want same-run deduplication only.
    """

    __slots__ = ("_database_path", "_connection", "_ttl_seconds", "_max_entries", "_memory")

    def __init__(
        self,
        database_path: Path | None,
        *,
        ttl_seconds: float = 900.0,
        max_entries: int = 500,
    ) -> None:
        if database_path is not None and not isinstance(database_path, PurePath):
            raise TypeError("database_path must be a pathlib.Path object or None.")

        self._database_path = database_path
        self._connection: sqlite3.Connection | None = None
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._memory: dict[str, tuple[float, tuple[SearchResult, ...]]] = {}

    def initialize(self) -> None:
        if self._database_path is None or self._connection is not None:
            return

        try:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)

            self._connection = sqlite3.connect(database=self._database_path)
            self._connection.row_factory = sqlite3.Row

            self._connection.execute("PRAGMA journal_mode = WAL;")
            self._connection.execute("PRAGMA synchronous = NORMAL;")
            self._connection.execute(
                f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS};"
            )
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS search_cache (
                    cache_key TEXT PRIMARY KEY,
                    results TEXT NOT NULL,
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
            raise SearchResultCacheError(
                "Failed to shut down search result cache."
            ) from ex
        finally:
            self._connection = None

    def get(self, key: str) -> tuple[SearchResult, ...] | None:
        """Return cached results for `key`, or None if absent/expired."""

        now = time.time()

        memory_entry = self._memory.get(key)

        if memory_entry is not None:
            cached_at, results = memory_entry

            if now - cached_at <= self._ttl_seconds:
                return results

            del self._memory[key]

        if self._connection is None:
            return None

        try:
            row = self._connection.execute(
                "SELECT results, cached_at FROM search_cache WHERE cache_key = ?;",
                (key,),
            ).fetchone()

        except sqlite3.Error as ex:
            raise SearchResultCacheError(
                "Failed to read from search result cache."
            ) from ex

        if row is None:
            return None

        if now - float(row["cached_at"]) > self._ttl_seconds:
            self._delete(key)
            return None

        results = _deserialize(row["results"])
        self._memory[key] = (float(row["cached_at"]), results)

        return results

    def set(self, key: str, results: tuple[SearchResult, ...]) -> None:
        """Store `results` under `key`, evicting the oldest entry if full."""

        now = time.time()
        self._memory[key] = (now, results)

        if len(self._memory) > self._max_entries:
            oldest_key = min(self._memory, key=lambda k: self._memory[k][0])
            del self._memory[oldest_key]

        if self._connection is None:
            return

        try:
            self._connection.execute(
                "INSERT OR REPLACE INTO search_cache (cache_key, results, cached_at) "
                "VALUES (?, ?, ?);",
                (key, _serialize(results), now),
            )
            self._connection.execute(
                """
                DELETE FROM search_cache WHERE cache_key NOT IN (
                    SELECT cache_key FROM search_cache
                    ORDER BY cached_at DESC LIMIT ?
                );
                """,
                (self._max_entries,),
            )
            self._connection.commit()

        except sqlite3.Error as ex:
            self._connection.rollback()
            raise SearchResultCacheError(
                "Failed to write to search result cache."
            ) from ex

    def _delete(self, key: str) -> None:
        if self._connection is None:
            return

        try:
            self._connection.execute(
                "DELETE FROM search_cache WHERE cache_key = ?;", (key,)
            )
            self._connection.commit()
        except sqlite3.Error:
            self._connection.rollback()


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


def _deserialize(payload: str) -> tuple[SearchResult, ...]:
    return tuple(
        SearchResult(
            title=item["title"], url=item["url"],
            snippet=item.get("snippet"), display_url=item.get("display_url"),
        )
        for item in json.loads(payload)
    )
