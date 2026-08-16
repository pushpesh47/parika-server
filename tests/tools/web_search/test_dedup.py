"""
Unit tests for `parika.tools.web_search.dedup`.
"""

from __future__ import annotations

from parika.tools.web_search.dedup import deduplicate_results, normalize_url
from parika.tools.web_search.search_result import SearchResult


class TestNormalizeUrl:
    def test_strips_www_and_trailing_slash(self) -> None:
        assert normalize_url("https://www.example.com/page/") == (
            "https://example.com/page"
        )

    def test_strips_tracking_parameters(self) -> None:
        assert normalize_url(
            "https://example.com/page?utm_source=x&id=1"
        ) == "https://example.com/page?id=1"

    def test_sorts_remaining_query_parameters(self) -> None:
        first = normalize_url("https://example.com/page?b=2&a=1")
        second = normalize_url("https://example.com/page?a=1&b=2")

        assert first == second

    def test_http_and_https_normalize_the_same(self) -> None:
        assert normalize_url("http://example.com/page") == normalize_url(
            "https://example.com/page"
        )


class TestDeduplicateResults:
    def test_removes_exact_url_duplicates(self) -> None:
        a = SearchResult(title="A", url="https://example.com/page")
        b = SearchResult(title="A (dup)", url="https://www.example.com/page/")

        result = deduplicate_results([a, b])

        assert result == (a,)

    def test_removes_tracking_parameter_duplicates(self) -> None:
        a = SearchResult(title="A", url="https://example.com/page?utm_source=x")
        b = SearchResult(title="A", url="https://example.com/page?fbclid=y")

        result = deduplicate_results([a, b])

        assert len(result) == 1

    def test_removes_same_domain_near_duplicate_titles(self) -> None:
        a = SearchResult(title="PARIKA Kernel Overview", url="https://example.com/a")
        b = SearchResult(
            title="PARIKA Kernel Overview!", url="https://example.com/b"
        )

        result = deduplicate_results([a, b])

        assert len(result) == 1
        assert result[0] is a

    def test_keeps_similar_titles_from_different_domains(self) -> None:
        a = SearchResult(title="PARIKA Kernel Overview", url="https://example.com/a")
        b = SearchResult(
            title="PARIKA Kernel Overview!", url="https://other.com/b"
        )

        result = deduplicate_results([a, b])

        assert len(result) == 2

    def test_preserves_order_of_kept_results(self) -> None:
        a = SearchResult(title="A", url="https://a.example/")
        b = SearchResult(title="B", url="https://b.example/")
        c = SearchResult(title="C", url="https://c.example/")

        result = deduplicate_results([a, b, c])

        assert result == (a, b, c)

    def test_empty_input_returns_empty(self) -> None:
        assert deduplicate_results([]) == ()

    def test_custom_threshold_is_respected(self) -> None:
        a = SearchResult(title="Completely Different Title", url="https://example.com/a")
        b = SearchResult(title="Totally Unrelated Text", url="https://example.com/b")

        # With an artificially low threshold, even unrelated titles on
        # the same domain would be treated as duplicates.
        result = deduplicate_results(
            [a, b], title_similarity_threshold=0.01
        )

        assert len(result) == 1
