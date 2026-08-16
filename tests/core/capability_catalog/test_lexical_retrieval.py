"""
Unit tests for `parika.core.capability_catalog.lexical_retrieval`.
"""

from __future__ import annotations

from parika.core.capability_catalog.lexical_retrieval import (
    TokenOverlapScorer,
    score_candidates,
)
from parika.core.capability_registry.capability_category import (
    CapabilityCategory,
)
from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)


def _definition(capability_id: str, *, keywords: frozenset[str]) -> CapabilityDefinition:
    return CapabilityDefinition(
        id=capability_id,
        name=capability_id,
        description="",
        category=CapabilityCategory.TOOL,
        keywords=keywords,
    )


class TestScoreIsBoundedForFutureSemanticCompatibility:
    def test_score_never_exceeds_one(self) -> None:
        """
        A capability whose entire (tiny) discovery vocabulary is a
        single word that also appears in the query would previously
        score slightly above 1.0 (coverage=1.0 plus the absolute
        overlap bonus). Scores must stay within the canonical
        `[0.0, 1.0]` range every other score source (including a
        future `SemanticScorer`) is expected to share.
        """

        definition = _definition("tiny.capability", keywords=frozenset({"ping"}))

        score = TokenOverlapScorer().score(
            definition, query_tokens=frozenset({"ping"})
        )

        assert score <= 1.0

    def test_score_is_never_negative(self) -> None:
        definition = _definition("weather.current", keywords=frozenset({"weather"}))

        score = TokenOverlapScorer().score(
            definition, query_tokens=frozenset({"unrelated"})
        )

        assert score >= 0.0


class TestScoreCandidates:
    def test_returns_zero_for_every_candidate_when_text_is_empty(self) -> None:
        definition = _definition("weather.current", keywords=frozenset({"weather"}))

        scores = score_candidates((definition,), text="")

        assert scores == {"weather.current": 0.0}

    def test_higher_overlap_scores_higher(self) -> None:
        strong = _definition(
            "weather.current", keywords=frozenset({"weather", "forecast"})
        )
        weak = _definition("currency.convert", keywords=frozenset({"currency"}))

        scores = score_candidates(
            (strong, weak), text="What's the weather forecast today?"
        )

        assert scores["weather.current"] > scores["currency.convert"]

    def test_every_score_stays_within_zero_to_one(self) -> None:
        definitions = tuple(
            CapabilityDefinition(
                id=f"capability.{index}",
                name="Weather Current",
                description="Returns current weather conditions.",
                category=CapabilityCategory.TOOL,
            )
            for index in range(5)
        )

        scores = score_candidates(definitions, text="current weather current")

        assert all(0.0 <= score <= 1.0 for score in scores.values())


class TestFieldWeighting:
    """
    A match in a capability's own `name`/`aliases` must count for more
    than the same word only appearing in free-form `description`/
    `examples` prose -- this is what lets a query correctly favor a
    capability whose *identity* matches over one that merely mentions
    the word in passing (e.g. "...using the current exchange rate").
    """

    def test_a_name_match_outranks_a_description_only_match(self) -> None:
        matches_by_name = CapabilityDefinition(
            id="weather.current",
            name="Weather Current",
            description="Returns current weather conditions for a location.",
            category=CapabilityCategory.TOOL,
            tags=frozenset({"weather"}),
        )
        matches_only_by_description = CapabilityDefinition(
            id="runtime.current_datetime",
            name="Runtime Info",
            description=(
                "Returns the current date and time from the system clock."
            ),
            category=CapabilityCategory.TOOL,
            tags=frozenset({"runtime"}),
        )
        # Filler candidates so document frequency reflects a
        # realistic-sized batch rather than a two-item corpus.
        filler = tuple(
            CapabilityDefinition(
                id=f"filler.{index}",
                name=f"Filler {index}",
                description="Does something unrelated entirely.",
                category=CapabilityCategory.TOOL,
            )
            for index in range(10)
        )

        scores = score_candidates(
            (matches_by_name, matches_only_by_description) + filler,
            text="current weather in patna bihar",
        )

        assert (
            scores["weather.current"]
            > scores["runtime.current_datetime"] * 2
        )


class TestInverseDocumentFrequency:
    """
    A query token shared by many candidates' discovery text must
    contribute less to each of their scores than a token unique (or
    near-unique) to one candidate -- standard IDF weighting, computed
    fresh from the current candidate batch, never a fixed list.
    """

    def test_a_common_token_contributes_less_than_a_rare_one(self) -> None:
        rare_match = CapabilityDefinition(
            id="weather.current",
            name="Weather Current",
            description="Returns current weather conditions for a location.",
            category=CapabilityCategory.TOOL,
        )
        common_token_only = tuple(
            CapabilityDefinition(
                id=f"common.{index}",
                name=f"Common {index}",
                description="Uses the current value for something else.",
                category=CapabilityCategory.TOOL,
            )
            for index in range(10)
        )

        scores = score_candidates(
            (rare_match,) + common_token_only, text="current weather"
        )

        # "weather" is unique to the rare match; "current" is shared
        # by all 11 candidates. The rare match's combined score (both
        # tokens, one of them highly discriminating) must clearly
        # outrank a candidate that only shares the common token.
        assert scores["weather.current"] > scores["common.0"] * 2


class TestSingularization:
    """
    A query using one inflected form should still match a capability
    whose discovery text uses another (e.g. "email" / "emails") --
    lightweight, generic, language-general normalization, never
    capability-specific.
    """

    def test_singular_query_matches_plural_discovery_text(self) -> None:
        definition = CapabilityDefinition(
            id="document.extract_contacts",
            name="Document - Extract Contacts",
            description=(
                "Extracts contact details (emails, URLs, phone numbers) "
                "found in a local document's text."
            ),
            category=CapabilityCategory.TOOL,
        )

        scores = score_candidates((definition,), text="fetch the email from pdf")

        assert scores["document.extract_contacts"] > 0.0

    def test_plural_query_matches_singular_discovery_text(self) -> None:
        definition = CapabilityDefinition(
            id="weather.current",
            name="Weather Current",
            description="Returns current weather conditions for a location.",
            category=CapabilityCategory.TOOL,
        )

        scores = score_candidates((definition,), text="weather conditions")

        assert scores["weather.current"] > 0.0

    def test_does_not_mangle_short_words(self) -> None:
        definition = CapabilityDefinition(
            id="news.latest",
            name="News Latest",
            description="Returns the latest general news headlines.",
            category=CapabilityCategory.TOOL,
        )

        # "news" must never be singularized down to "new".
        scores = score_candidates((definition,), text="news")

        assert scores["news.latest"] > 0.0


class TestGenericStopwordsAreExcluded:
    def test_a_shared_preposition_does_not_create_a_false_positive(self) -> None:
        """
        Regression test: "from" (and similarly common prepositions)
        must never register as a lexical signal purely because it
        appears in unrelated capabilities' description prose.
        """

        unrelated = CapabilityDefinition(
            id="news.latest",
            name="News Latest",
            description="Returns the latest headlines from configured feeds.",
            category=CapabilityCategory.TOOL,
        )

        scores = score_candidates((unrelated,), text="fetch the email from pdf")

        assert scores["news.latest"] == 0.0
