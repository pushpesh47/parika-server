"""
Unit tests for `parika.tools.web_search.ranking`.
"""

from __future__ import annotations

from parika.tools.web_search.ranking import RankingWeights, rank_results
from parika.tools.web_search.search_result import SearchResult


def _result(title: str, snippet: str | None = None) -> SearchResult:
    return SearchResult(title=title, url=f"https://example.com/{title}", snippet=snippet)


class TestRankResults:
    def test_empty_input_returns_empty_tuple(self) -> None:
        assert rank_results("anything", ()) == ()

    def test_preserves_order_when_no_result_matches_the_query(self) -> None:
        results = (
            _result("Completely unrelated"),
            _result("Also unrelated"),
        )

        assert rank_results("parika kernel", results) == results

    def test_more_relevant_result_moves_ahead_of_less_relevant_one(
        self,
    ) -> None:
        """
        Regression test for Issue 6/7: a highly relevant result that
        happens to appear late in the backend's own order (e.g. rank
        10) must be promoted ahead of a barely-relevant result that
        happened to appear first - so a caller that ultimately
        truncates the ranked list never discards it.
        """

        barely_relevant = _result(
            "Some other page", snippet="Nothing to do with the query."
        )
        highly_relevant = _result(
            "PARIKA intelligence kernel architecture",
            snippet="A deep dive into the PARIKA kernel design.",
        )

        # highly_relevant is deliberately placed *last*, as if the
        # backend itself ranked it 10th.
        results = (barely_relevant,) * 9 + (highly_relevant,)

        ranked = rank_results("parika intelligence kernel", results)

        assert ranked[0] is highly_relevant

    def test_title_overlap_outweighs_snippet_overlap(self) -> None:
        title_match = _result("parika kernel", snippet="unrelated text")
        snippet_match = _result(
            "unrelated title", snippet="mentions parika kernel here"
        )

        ranked = rank_results(
            "parika kernel", (snippet_match, title_match)
        )

        assert ranked[0] is title_match

    def test_stable_for_ties_preserving_backend_order(self) -> None:
        first = _result("Alpha result")
        second = _result("Beta result")

        ranked = rank_results("unrelated query terms", (first, second))

        assert ranked == (first, second)

    def test_custom_weights_are_honored(self) -> None:
        title_match = _result("parika", snippet="nothing relevant")
        snippet_match = _result("nothing relevant", snippet="parika")

        # With snippet weighted far higher than title, the
        # snippet-matching result should win instead.
        weights = RankingWeights(
            title_weight=0.1, snippet_weight=5.0, position_decay=0.01
        )

        ranked = rank_results(
            "parika", (title_match, snippet_match), weights=weights
        )

        assert ranked[0] is snippet_match

    def test_case_insensitive_matching(self) -> None:
        result = _result("PARIKA Kernel")

        ranked = rank_results("parika kernel", (result,))

        assert ranked == (result,)

    def test_stopwords_do_not_drive_relevance(self) -> None:
        no_real_overlap = _result("the of in and")
        real_overlap = _result("about the parika project")

        ranked = rank_results("the of parika", (no_real_overlap, real_overlap))

        assert ranked[0] is real_overlap
