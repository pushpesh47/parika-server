"""
Unit tests for WebSearchToolDriver.
"""

from __future__ import annotations

from typing import Any

import pytest

from parika.core.tool_manager.request import ToolRequest
from parika.tools.web_search.driver import WebSearchToolDriver
from parika.tools.web_search.exceptions import (
    InvalidSearchQueryError,
    WebSearchToolError,
)
from parika.tools.web_search.manifest import (
    WEB_SEARCH_CAPABILITY_ID,
    WEB_SEARCH_TOOL_ID,
    create_web_search_tool,
)
from parika.tools.web_search.page_content import PageContent
from parika.tools.web_search.search_result import SearchResult


class _FakeSearchBackend:
    def __init__(self, results: tuple[SearchResult, ...]) -> None:
        self.results = results
        self.calls: list[tuple[str, int]] = []

    def search(
        self,
        query: str,
        *,
        max_results: int,
    ) -> tuple[SearchResult, ...]:
        self.calls.append((query, max_results))
        return self.results


class _FakePageFetcher:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self._pages: dict[str, PageContent | Exception] = {}

    def set_page(self, url: str, page: PageContent) -> None:
        self._pages[url] = page

    def set_failure(self, url: str, error: Exception) -> None:
        self._pages[url] = error

    def fetch(self, url: str) -> PageContent:
        self.calls.append(url)

        outcome = self._pages[url]

        if isinstance(outcome, Exception):
            raise outcome

        return outcome


def _page(url: str) -> PageContent:
    return PageContent(
        url=url,
        final_url=url,
        status_code=200,
        title="Title",
        description="Description",
        text="Body text.",
        content_type="text/html",
        content_length=100,
    )


class TestExecute:
    def test_returns_results_without_content(self) -> None:
        results = (
            SearchResult(title="A", url="https://a.example", snippet="a"),
            SearchResult(title="B", url="https://b.example", snippet="b"),
        )
        backend = _FakeSearchBackend(results)
        fetcher = _FakePageFetcher()

        driver = WebSearchToolDriver(
            search_backend=backend,  # type: ignore[arg-type]
            page_fetcher=fetcher,  # type: ignore[arg-type]
        )

        response = driver.execute(
            ToolRequest(arguments={"query": "parika"})
        )

        assert response.attributes["query"] == "parika"
        assert response.attributes["result_count"] == 2
        assert response.result[0]["title"] == "A"
        assert "page" not in response.result[0]
        assert fetcher.calls == []
        # The backend is asked for a generous candidate pool - not
        # just the final `default_max_results` count - so ranking has
        # real headroom to promote a relevant result the backend
        # reported near the end of its own order (Issue 6/7); the
        # driver itself still only *returns* `default_max_results`.
        assert backend.calls == [("parika", 20)]

    def test_respects_max_results_argument(self) -> None:
        backend = _FakeSearchBackend(())
        fetcher = _FakePageFetcher()

        driver = WebSearchToolDriver(
            search_backend=backend,  # type: ignore[arg-type]
            page_fetcher=fetcher,  # type: ignore[arg-type]
        )

        driver.execute(
            ToolRequest(arguments={"query": "parika", "max_results": 2})
        )

        # The candidate pool requested from the backend is always at
        # least `candidate_pool_size` (default 20), even when the
        # caller asked for fewer final results.
        assert backend.calls == [("parika", 20)]

    def test_candidate_pool_size_grows_with_a_larger_max_results(
        self,
    ) -> None:
        backend = _FakeSearchBackend(())
        fetcher = _FakePageFetcher()

        driver = WebSearchToolDriver(
            search_backend=backend,  # type: ignore[arg-type]
            page_fetcher=fetcher,  # type: ignore[arg-type]
            candidate_pool_size=20,
        )

        driver.execute(
            ToolRequest(arguments={"query": "parika", "max_results": 30})
        )

        assert backend.calls == [("parika", 30)]

    def test_ranking_promotes_a_relevant_result_from_a_low_rank(
        self,
    ) -> None:
        """
        Regression test for Issue 6/7: a highly relevant result the
        backend reported near the end of its own order must still be
        returned once truncated to a smaller `max_results`, because
        ranking runs *before* truncation.
        """

        barely_relevant = SearchResult(
            title="Unrelated", url="https://x.example", snippet="Nothing."
        )
        highly_relevant = SearchResult(
            title="PARIKA intelligence kernel",
            url="https://parika.example",
            snippet="All about the PARIKA kernel.",
        )
        backend = _FakeSearchBackend(
            (barely_relevant,) * 9 + (highly_relevant,)
        )
        fetcher = _FakePageFetcher()

        driver = WebSearchToolDriver(
            search_backend=backend,  # type: ignore[arg-type]
            page_fetcher=fetcher,  # type: ignore[arg-type]
        )

        response = driver.execute(
            ToolRequest(
                arguments={
                    "query": "parika intelligence kernel",
                    "max_results": 1,
                }
            )
        )

        assert response.result[0]["title"] == "PARIKA intelligence kernel"

    def test_ranking_disabled_preserves_raw_backend_order(self) -> None:
        first = SearchResult(title="Unrelated", url="https://x.example")
        second = SearchResult(title="parika", url="https://parika.example")
        backend = _FakeSearchBackend((first, second))
        fetcher = _FakePageFetcher()

        driver = WebSearchToolDriver(
            search_backend=backend,  # type: ignore[arg-type]
            page_fetcher=fetcher,  # type: ignore[arg-type]
            ranking_enabled=False,
        )

        response = driver.execute(
            ToolRequest(arguments={"query": "parika"})
        )

        assert response.result[0]["title"] == "Unrelated"

    def test_default_max_results_is_configurable(self) -> None:
        results = tuple(
            SearchResult(title=f"Result {i}", url=f"https://example.com/{i}")
            for i in range(15)
        )
        backend = _FakeSearchBackend(results)
        fetcher = _FakePageFetcher()

        driver = WebSearchToolDriver(
            search_backend=backend,  # type: ignore[arg-type]
            page_fetcher=fetcher,  # type: ignore[arg-type]
            default_max_results=3,
        )

        response = driver.execute(
            ToolRequest(arguments={"query": "parika"})
        )

        assert response.attributes["result_count"] == 3

    def test_enriches_results_with_page_content_when_requested(
        self,
    ) -> None:
        results = (
            SearchResult(title="A", url="https://a.example", snippet="a"),
        )
        backend = _FakeSearchBackend(results)
        fetcher = _FakePageFetcher()
        fetcher.set_page("https://a.example", _page("https://a.example"))

        driver = WebSearchToolDriver(
            search_backend=backend,  # type: ignore[arg-type]
            page_fetcher=fetcher,  # type: ignore[arg-type]
        )

        response = driver.execute(
            ToolRequest(
                arguments={"query": "parika", "include_content": True}
            )
        )

        assert fetcher.calls == ["https://a.example"]
        assert response.result[0]["page"]["title"] == "Title"

    def test_page_fetch_failure_is_tolerated(self) -> None:
        results = (
            SearchResult(title="A", url="https://a.example", snippet="a"),
        )
        backend = _FakeSearchBackend(results)
        fetcher = _FakePageFetcher()
        fetcher.set_failure(
            "https://a.example", WebSearchToolError("unreachable")
        )

        driver = WebSearchToolDriver(
            search_backend=backend,  # type: ignore[arg-type]
            page_fetcher=fetcher,  # type: ignore[arg-type]
        )

        response = driver.execute(
            ToolRequest(
                arguments={"query": "parika", "include_content": True}
            )
        )

        # Best-effort: the search itself still succeeds.
        assert response.attributes["result_count"] == 1
        assert "page" not in response.result[0]

    def test_rejects_missing_query(self) -> None:
        backend = _FakeSearchBackend(())
        fetcher = _FakePageFetcher()

        driver = WebSearchToolDriver(
            search_backend=backend,  # type: ignore[arg-type]
            page_fetcher=fetcher,  # type: ignore[arg-type]
        )

        with pytest.raises(InvalidSearchQueryError):
            driver.execute(ToolRequest(arguments={}))

    def test_rejects_empty_query(self) -> None:
        backend = _FakeSearchBackend(())
        fetcher = _FakePageFetcher()

        driver = WebSearchToolDriver(
            search_backend=backend,  # type: ignore[arg-type]
            page_fetcher=fetcher,  # type: ignore[arg-type]
        )

        with pytest.raises(InvalidSearchQueryError):
            driver.execute(ToolRequest(arguments={"query": "   "}))


class TestDeduplication:
    def test_duplicate_results_are_removed_before_max_results_slicing(
        self,
    ) -> None:
        duplicate = SearchResult(
            title="PARIKA", url="https://parika.example/?utm_source=x"
        )
        duplicate_again = SearchResult(
            title="PARIKA", url="https://www.parika.example/"
        )
        distinct = SearchResult(title="Other", url="https://other.example/")

        backend = _FakeSearchBackend((duplicate, duplicate_again, distinct))
        fetcher = _FakePageFetcher()

        driver = WebSearchToolDriver(
            search_backend=backend,  # type: ignore[arg-type]
            page_fetcher=fetcher,  # type: ignore[arg-type]
            ranking_enabled=False,
        )

        response = driver.execute(
            ToolRequest(arguments={"query": "parika", "max_results": 10})
        )

        assert response.attributes["result_count"] == 2

    def test_dedup_disabled_preserves_duplicates(self) -> None:
        duplicate = SearchResult(title="PARIKA", url="https://parika.example/")
        duplicate_again = SearchResult(
            title="PARIKA", url="https://www.parika.example/"
        )

        backend = _FakeSearchBackend((duplicate, duplicate_again))
        fetcher = _FakePageFetcher()

        driver = WebSearchToolDriver(
            search_backend=backend,  # type: ignore[arg-type]
            page_fetcher=fetcher,  # type: ignore[arg-type]
            ranking_enabled=False,
            dedup_enabled=False,
        )

        response = driver.execute(
            ToolRequest(arguments={"query": "parika", "max_results": 10})
        )

        assert response.attributes["result_count"] == 2


class TestQueryNormalizationAndValidation:
    def test_ambiguous_role_query_is_normalized_before_dispatch(
        self,
    ) -> None:
        """
        Regression test for Phase 1 Item 1: "current prime minister
        of Japan" must reach the backend as "incumbent prime
        minister of Japan", never the raw, ambiguous wording.
        """

        results = (
            SearchResult(
                title="Incumbent Prime Minister of Japan",
                url="https://gov.example/pm",
                snippet="The incumbent prime minister of Japan is ...",
            ),
        )
        backend = _FakeSearchBackend(results)
        fetcher = _FakePageFetcher()

        driver = WebSearchToolDriver(
            search_backend=backend,  # type: ignore[arg-type]
            page_fetcher=fetcher,  # type: ignore[arg-type]
        )

        response = driver.execute(
            ToolRequest(
                arguments={"query": "current prime minister of Japan"}
            )
        )

        assert backend.calls == [
            ("incumbent prime minister of Japan", 20)
        ]
        # attributes["query"] still reports the caller's exact,
        # original input for backward compatibility.
        assert response.attributes["query"] == (
            "current prime minister of Japan"
        )
        assert response.attributes["validation"]["rewritten_query"] == (
            "incumbent prime minister of Japan"
        )

    def test_unambiguous_query_reports_no_rewritten_query(self) -> None:
        results = (
            SearchResult(title="PARIKA", url="https://parika.example/"),
        )
        backend = _FakeSearchBackend(results)
        fetcher = _FakePageFetcher()

        driver = WebSearchToolDriver(
            search_backend=backend,  # type: ignore[arg-type]
            page_fetcher=fetcher,  # type: ignore[arg-type]
        )

        response = driver.execute(
            ToolRequest(arguments={"query": "parika"})
        )

        assert backend.calls == [("parika", 20)]
        assert response.attributes["validation"]["rewritten_query"] is None

    def test_low_confidence_results_are_still_returned_gracefully(
        self,
    ) -> None:
        """
        A search that never becomes confident must still return a
        response - never raise - annotated with
        `low_confidence=True`, so callers/models can decide how to
        present it rather than receiving nothing at all.
        """

        results = (
            SearchResult(title="A", url="https://a.example", snippet="a"),
        )
        backend = _FakeSearchBackend(results)
        fetcher = _FakePageFetcher()

        driver = WebSearchToolDriver(
            search_backend=backend,  # type: ignore[arg-type]
            page_fetcher=fetcher,  # type: ignore[arg-type]
        )

        response = driver.execute(
            ToolRequest(arguments={"query": "parika"})
        )

        assert response.attributes["result_count"] == 1
        assert response.attributes["validation"]["low_confidence"] is True
        assert response.attributes["validation"]["confidence"] == 0.0

    def test_retry_fires_when_the_rewritten_query_genuinely_differs(
        self,
    ) -> None:
        """
        When the first attempt's query still has something left for
        `rewrite_for_retry()` to strip (here, trailing punctuation),
        a second, genuinely different backend call is made.
        """

        backend = _FakeSearchBackend(())
        fetcher = _FakePageFetcher()

        driver = WebSearchToolDriver(
            search_backend=backend,  # type: ignore[arg-type]
            page_fetcher=fetcher,  # type: ignore[arg-type]
        )

        driver.execute(ToolRequest(arguments={"query": "parika?"}))

        assert backend.calls == [
            ("parika?", 20),
            ("parika", 20),
        ]

    def test_retry_is_skipped_when_rewrite_is_identical(self) -> None:
        """
        Regression test: when there is nothing left for
        `rewrite_for_retry()` to strip, no second backend call is
        made, preserving single-call behavior for ordinary,
        low-relevance test fixtures.
        """

        backend = _FakeSearchBackend(())
        fetcher = _FakePageFetcher()

        driver = WebSearchToolDriver(
            search_backend=backend,  # type: ignore[arg-type]
            page_fetcher=fetcher,  # type: ignore[arg-type]
        )

        driver.execute(ToolRequest(arguments={"query": "parika"}))

        assert backend.calls == [("parika", 20)]

    def test_confident_result_reports_low_confidence_false(self) -> None:
        results = (
            SearchResult(
                title="parika intelligence kernel",
                url="https://parika.example/",
                snippet="All about the PARIKA kernel.",
            ),
        )
        backend = _FakeSearchBackend(results)
        fetcher = _FakePageFetcher()

        driver = WebSearchToolDriver(
            search_backend=backend,  # type: ignore[arg-type]
            page_fetcher=fetcher,  # type: ignore[arg-type]
        )

        response = driver.execute(
            ToolRequest(arguments={"query": "parika intelligence kernel"})
        )

        assert response.attributes["validation"]["low_confidence"] is False
        assert response.attributes["validation"]["retried"] is False

    def test_validation_disabled_skips_normalization_and_gating(
        self,
    ) -> None:
        """
        `validation_enabled=False` is a full kill switch: the raw
        query reaches the backend completely unmodified, and no
        `attributes["validation"]` key is added at all.
        """

        results = (
            SearchResult(title="A", url="https://a.example", snippet="a"),
        )
        backend = _FakeSearchBackend(results)
        fetcher = _FakePageFetcher()

        driver = WebSearchToolDriver(
            search_backend=backend,  # type: ignore[arg-type]
            page_fetcher=fetcher,  # type: ignore[arg-type]
            validation_enabled=False,
        )

        response = driver.execute(
            ToolRequest(
                arguments={"query": "current prime minister of Japan"}
            )
        )

        assert backend.calls == [
            ("current prime minister of Japan", 20)
        ]
        assert "validation" not in response.attributes


class TestManifest:
    def test_create_web_search_tool_matches_constants(self) -> None:
        tool = create_web_search_tool()

        assert tool.id == WEB_SEARCH_TOOL_ID
        assert tool.capabilities == (WEB_SEARCH_CAPABILITY_ID,)
        assert tool.enabled
