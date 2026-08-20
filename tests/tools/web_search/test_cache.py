"""Unit tests for SearchResultCache and make_cache_key()."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from parika.tools.web_search.cache import InMemorySearchResultCache, make_cache_key
from parika.tools.web_search.search_result import SearchResult


def _results(*titles: str) -> tuple[SearchResult, ...]:
    return tuple(
        SearchResult(title=title, url=f"https://example.com/{title}")
        for title in titles
    )


class TestMakeCacheKey:
    def test_normalizes_case_and_whitespace(self) -> None:
        assert make_cache_key("  Hello   World  ", "backend") == make_cache_key(
            "hello world", "backend"
        )

    def test_different_backends_produce_different_keys(self) -> None:
        assert make_cache_key("x", "a") != make_cache_key("x", "b")


class TestInMemoryOnly:
    def test_set_then_get_returns_results(self) -> None:
        cache = InMemorySearchResultCache(ttl_seconds=100)
        results = _results("a", "b")

        cache.set("key", results)

        assert cache.get("key") == results

    def test_get_missing_key_returns_none(self) -> None:
        cache = InMemorySearchResultCache()

        assert cache.get("missing") is None

    def test_expired_entry_returns_none(self) -> None:
        cache = InMemorySearchResultCache(ttl_seconds=0.0)
        cache.set("key", _results("a"))

        import time

        time.sleep(0.01)

        assert cache.get("key") is None

    def test_max_entries_evicts_oldest(self) -> None:
        cache = InMemorySearchResultCache(ttl_seconds=1000, max_entries=2)

        cache.set("k1", _results("a"))
        cache.set("k2", _results("b"))
        cache.set("k3", _results("c"))

        assert cache.get("k1") is None
        assert cache.get("k2") is not None
        assert cache.get("k3") is not None
