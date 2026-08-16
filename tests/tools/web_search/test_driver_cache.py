"""
Unit tests for WebSearchToolDriver's optional SearchResultCache
integration.
"""

from __future__ import annotations

import pytest

from parika.core.tool_manager.request import ToolRequest
from parika.tools.web_search.cache import SearchResultCache
from parika.tools.web_search.driver import WebSearchToolDriver
from parika.tools.web_search.search_result import SearchResult


class _FakeSearchBackend:
    def __init__(self, results: tuple[SearchResult, ...]) -> None:
        self.results = results
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, *, max_results: int) -> tuple[SearchResult, ...]:
        self.calls.append((query, max_results))
        return self.results


class _FakePageFetcher:
    def fetch(self, url: str):
        raise NotImplementedError


@pytest.fixture
def cache() -> SearchResultCache:
    cache = SearchResultCache(None, ttl_seconds=1000)
    cache.initialize()
    return cache


class TestDriverCaching:
    def test_no_cache_hits_backend_every_time(self) -> None:
        backend = _FakeSearchBackend(
            (SearchResult(title="A", url="https://a.example"),)
        )
        driver = WebSearchToolDriver(
            search_backend=backend,  # type: ignore[arg-type]
            page_fetcher=_FakePageFetcher(),  # type: ignore[arg-type]
            validation_enabled=False,
            ranking_enabled=False,
            dedup_enabled=False,
        )

        driver.execute(ToolRequest(arguments={"query": "parika"}))
        driver.execute(ToolRequest(arguments={"query": "parika"}))

        assert len(backend.calls) == 2

    def test_cache_avoids_second_backend_call(self, cache: SearchResultCache) -> None:
        backend = _FakeSearchBackend(
            (SearchResult(title="A", url="https://a.example"),)
        )
        driver = WebSearchToolDriver(
            search_backend=backend,  # type: ignore[arg-type]
            page_fetcher=_FakePageFetcher(),  # type: ignore[arg-type]
            validation_enabled=False,
            ranking_enabled=False,
            dedup_enabled=False,
            cache=cache,
        )

        first = driver.execute(ToolRequest(arguments={"query": "parika"}))
        second = driver.execute(ToolRequest(arguments={"query": "parika"}))

        assert len(backend.calls) == 1
        assert first.result == second.result

    def test_different_queries_are_cached_separately(
        self, cache: SearchResultCache
    ) -> None:
        backend = _FakeSearchBackend((SearchResult(title="A", url="https://a.example"),))
        driver = WebSearchToolDriver(
            search_backend=backend,  # type: ignore[arg-type]
            page_fetcher=_FakePageFetcher(),  # type: ignore[arg-type]
            validation_enabled=False,
            ranking_enabled=False,
            dedup_enabled=False,
            cache=cache,
        )

        driver.execute(ToolRequest(arguments={"query": "alpha"}))
        driver.execute(ToolRequest(arguments={"query": "beta"}))

        assert len(backend.calls) == 2

    def test_case_and_whitespace_normalized_queries_share_a_cache_entry(
        self, cache: SearchResultCache
    ) -> None:
        backend = _FakeSearchBackend((SearchResult(title="A", url="https://a.example"),))
        driver = WebSearchToolDriver(
            search_backend=backend,  # type: ignore[arg-type]
            page_fetcher=_FakePageFetcher(),  # type: ignore[arg-type]
            validation_enabled=False,
            ranking_enabled=False,
            dedup_enabled=False,
            cache=cache,
        )

        driver.execute(ToolRequest(arguments={"query": "Parika Search"}))
        driver.execute(ToolRequest(arguments={"query": "  parika   search  "}))

        assert len(backend.calls) == 1
