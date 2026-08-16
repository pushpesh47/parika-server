"""
Unit tests for `parika.tools.web_search.validation`.
"""

from __future__ import annotations

from parika.tools.web_search.search_result import SearchResult
from parika.tools.web_search.validation import (
    SearchResultValidator,
    SearchValidationConfig,
)


class TestScoreResult:
    def test_relevant_title_scores_higher_than_unrelated_title(self) -> None:
        validator = SearchResultValidator()

        relevant = SearchResult(
            title="PARIKA intelligence kernel",
            url="https://parika.example/about",
            snippet="All about the PARIKA kernel.",
        )
        unrelated = SearchResult(
            title="Unrelated page",
            url="https://x.example/other",
            snippet="Nothing to do with the query.",
        )

        scored = dict(
            validator.score_results(
                "parika intelligence kernel", (relevant, unrelated)
            )
        )

        assert scored[relevant] > scored[unrelated]

    def test_full_title_overlap_meets_default_confidence_threshold(
        self,
    ) -> None:
        validator = SearchResultValidator()

        result = SearchResult(
            title="parika", url="https://parika.example/"
        )

        confidence = validator.score_result(
            frozenset({"parika"}), result
        )

        assert confidence >= validator.config.min_confidence

    def test_completely_unrelated_result_scores_zero(self) -> None:
        validator = SearchResultValidator()

        result = SearchResult(
            title="Electric current basics",
            url="https://physics.example/current",
            snippet="Understanding electric current and voltage.",
        )

        confidence = validator.score_result(
            frozenset({"prime", "minister", "japan"}), result
        )

        assert confidence == 0.0

    def test_zero_total_weight_scores_zero(self) -> None:
        validator = SearchResultValidator(
            SearchValidationConfig(
                title_weight=0.0, snippet_weight=0.0, url_weight=0.0
            )
        )

        result = SearchResult(title="parika", url="https://parika.example/")

        assert validator.score_result(frozenset({"parika"}), result) == 0.0


class TestBestConfidenceAndIsConfident:
    def test_empty_results_have_zero_confidence(self) -> None:
        validator = SearchResultValidator()

        assert validator.best_confidence("parika", ()) == 0.0
        assert validator.is_confident("parika", ()) is False

    def test_best_confidence_is_the_maximum_across_results(self) -> None:
        validator = SearchResultValidator()

        unrelated = SearchResult(title="Unrelated", url="https://x.example/")
        relevant = SearchResult(
            title="parika", url="https://parika.example/"
        )

        best = validator.best_confidence("parika", (unrelated, relevant))

        assert best == validator.score_result(
            frozenset({"parika"}), relevant
        )

    def test_is_confident_true_when_threshold_met(self) -> None:
        validator = SearchResultValidator(
            SearchValidationConfig(min_confidence=0.1)
        )
        relevant = SearchResult(
            title="parika", url="https://parika.example/"
        )

        assert validator.is_confident("parika", (relevant,)) is True

    def test_is_confident_false_when_below_threshold(self) -> None:
        validator = SearchResultValidator(
            SearchValidationConfig(min_confidence=0.9)
        )
        barely_relevant = SearchResult(
            title="something else entirely",
            url="https://x.example/",
            snippet="parika is mentioned once here",
        )

        assert validator.is_confident("parika", (barely_relevant,)) is False


class TestSearchValidationConfigDefaults:
    def test_default_config_values(self) -> None:
        config = SearchValidationConfig()

        assert config.min_confidence == 0.15
        assert config.max_retries == 1
        assert config.title_weight == 0.5
        assert config.snippet_weight == 0.3
        assert config.url_weight == 0.2
