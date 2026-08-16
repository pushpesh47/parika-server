"""
Unit tests for `parika.tools.web_search.query_normalizer`.
"""

from __future__ import annotations

import pytest

from parika.tools.web_search.query_normalizer import QueryNormalizer


@pytest.fixture
def normalizer() -> QueryNormalizer:
    return QueryNormalizer()


class TestNormalize:
    def test_unambiguous_query_is_returned_unchanged(
        self, normalizer: QueryNormalizer
    ) -> None:
        assert normalizer.normalize("parika") == "parika"

    def test_unrelated_current_usage_is_left_untouched(
        self, normalizer: QueryNormalizer
    ) -> None:
        assert (
            normalizer.normalize("current exchange rate for USD to INR")
            == "current exchange rate for USD to INR"
        )
        assert (
            normalizer.normalize("current weather in Tokyo")
            == "current weather in Tokyo"
        )

    def test_current_prime_minister_is_rewritten_to_incumbent(
        self, normalizer: QueryNormalizer
    ) -> None:
        assert (
            normalizer.normalize("current prime minister of Japan")
            == "incumbent prime minister of Japan"
        )

    def test_current_president_is_rewritten_to_incumbent(
        self, normalizer: QueryNormalizer
    ) -> None:
        assert (
            normalizer.normalize("current president of France")
            == "incumbent president of France"
        )

    def test_role_noun_casing_is_preserved(
        self, normalizer: QueryNormalizer
    ) -> None:
        assert (
            normalizer.normalize("Current President of France")
            == "incumbent President of France"
        )

    def test_leading_filler_phrase_is_stripped(
        self, normalizer: QueryNormalizer
    ) -> None:
        assert (
            normalizer.normalize("What is the current exchange rate for USD?")
            == "the current exchange rate for USD?"
        )
        assert (
            normalizer.normalize("Who is the current prime minister of Japan?")
            == "the incumbent prime minister of Japan?"
        )

    def test_chained_filler_phrases_are_fully_stripped(
        self, normalizer: QueryNormalizer
    ) -> None:
        assert (
            normalizer.normalize(
                "Please tell me about the current president of France"
            )
            == "the incumbent president of France"
        )

    def test_empty_query_falls_back_to_stripped_original(
        self, normalizer: QueryNormalizer
    ) -> None:
        assert normalizer.normalize("  parika  ") == "parika"


class TestDetectAmbiguity:
    def test_unambiguous_query_reports_no_facet(
        self, normalizer: QueryNormalizer
    ) -> None:
        assert normalizer.detect_ambiguity("parika") == (False, None)

    def test_current_role_pattern_reports_temporal_facet(
        self, normalizer: QueryNormalizer
    ) -> None:
        assert normalizer.detect_ambiguity(
            "current prime minister of Japan"
        ) == (True, "temporal")

    def test_current_without_role_noun_is_not_ambiguous(
        self, normalizer: QueryNormalizer
    ) -> None:
        assert normalizer.detect_ambiguity("current weather in Tokyo") == (
            False,
            None,
        )


class TestRewriteForRetry:
    def test_strips_trailing_punctuation(
        self, normalizer: QueryNormalizer
    ) -> None:
        assert normalizer.rewrite_for_retry("parika?") == "parika"

    def test_collapses_internal_punctuation_and_whitespace(
        self, normalizer: QueryNormalizer
    ) -> None:
        assert (
            normalizer.rewrite_for_retry("parika, kernel; architecture.")
            == "parika kernel architecture"
        )

    def test_returns_input_unchanged_when_nothing_to_strip(
        self, normalizer: QueryNormalizer
    ) -> None:
        assert normalizer.rewrite_for_retry("parika") == "parika"
