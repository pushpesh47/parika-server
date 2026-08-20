"""
PARIKA Web Search Tool - Result Cache

Caches the ranked (pre-page-fetch) candidate pool produced by
`WebSearchToolDriver._run_search_pipeline()`, keyed by a normalized
query and the backend's identity, with a TTL. This is the one real
gap identified in Advanced Search Improvements -- ranking, dedup,
validation, and query normalization already existed; only caching was
missing (see
docs/architecture/Intelligence_Foundation_Design.md section 10).

Backed by PostgreSQL for cross-run persistence plus an in-process dict
for same-run hits without a database round trip. Never caches page
content: only the pre-enrichment SearchResult pool, exactly what
`_run_search_pipeline()` produces.
"""

from __future__ import annotations

import json
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


class InMemorySearchResultCache:
    """
    In-memory TTL-based cache for ranked (pre-page-fetch) SearchResult pools.

    Used for testing and when PostgreSQL is not available.
    """

    __slots__ = ("_ttl_seconds", "_max_entries", "_memory")

    def __init__(
        self,
        *,
        ttl_seconds: float = 900.0,
        max_entries: int = 500,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._memory: dict[str, tuple[float, tuple[SearchResult, ...]]] = {}

    def initialize(self) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def get(self, key: str) -> tuple[SearchResult, ...] | None:
        now = time.time()
        memory_entry = self._memory.get(key)

        if memory_entry is not None:
            cached_at, results = memory_entry

            if now - cached_at <= self._ttl_seconds:
                return results

            del self._memory[key]

        return None

    def set(self, key: str, results: tuple[SearchResult, ...]) -> None:
        now = time.time()
        self._memory[key] = (now, results)

        if len(self._memory) > self._max_entries:
            oldest_key = min(self._memory, key=lambda k: self._memory[k][0])
            del self._memory[oldest_key]

    def _delete(self, key: str) -> None:
        self._memory.pop(key, None)


class SearchResultCache:
    """
    TTL-based cache for ranked (pre-page-fetch) SearchResult pools.

    This class now delegates to either PostgreSQL or in-memory storage.
    The actual implementation is selected at runtime by the caller.
    """

    __slots__ = ("_impl",)

    def __init__(
        self,
        database_path: Path | None,
        *,
        ttl_seconds: float = 900.0,
        max_entries: int = 500,
    ) -> None:
        if database_path is not None and not isinstance(database_path, PurePath):
            raise TypeError("database_path must be a pathlib.Path object or None.")

        # This is now a factory - actual implementation is created by the caller
        # with the appropriate pool. This class is kept for backward compatibility.
        self._impl = None

    def initialize(self) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def get(self, key: str) -> tuple[SearchResult, ...] | None:
        raise NotImplementedError("Use PostgreSQLSearchResultCache or InMemorySearchResultCache directly")

    def set(self, key: str, results: tuple[SearchResult, ...]) -> None:
        raise NotImplementedError("Use PostgreSQLSearchResultCache or InMemorySearchResultCache directly")

    def _delete(self, key: str) -> None:
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


def _deserialize(payload: str) -> tuple[SearchResult, ...]:
    return tuple(
        SearchResult(
            title=item["title"], url=item["url"],
            snippet=item.get("snippet"), display_url=item.get("display_url"),
        )
        for item in json.loads(payload)
    )
