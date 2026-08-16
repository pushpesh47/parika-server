"""
Unit tests for `parika.core.capability_catalog.family_ranking`.
"""

from __future__ import annotations

from parika.core.capability_catalog.family_ranking import rank_families
from parika.core.capability_registry.capability_category import (
    CapabilityCategory,
)
from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)


def _definition(capability_id: str, *, family: str | None) -> CapabilityDefinition:
    return CapabilityDefinition(
        id=capability_id,
        name=capability_id,
        description="",
        category=CapabilityCategory.TOOL,
        family=family,
    )


class TestMaxPoolingIsThePrimarySignal:
    def test_family_score_is_at_least_its_best_members_score(self) -> None:
        strong = _definition("document.summarize", family="document")
        weak = _definition("document.translate", family="document")

        family_scores = rank_families(
            (strong, weak), scores={"document.summarize": 0.9, "document.translate": 0.0}
        )

        assert family_scores["document"] >= 0.9

    def test_many_irrelevant_siblings_never_drag_a_strong_match_down(self) -> None:
        """
        Averaging would let a large family of otherwise-irrelevant
        members dilute one genuinely strong match. Max-pooling must
        not allow that.
        """

        strong = _definition("document.summarize", family="document")
        siblings = tuple(
            _definition(f"document.sibling_{index}", family="document")
            for index in range(20)
        )

        scores = {"document.summarize": 0.9}
        scores.update({sibling.id: 0.0 for sibling in siblings})

        family_scores = rank_families((strong,) + siblings, scores=scores)

        assert family_scores["document"] >= 0.9


class TestCoverageTieBreak:
    def test_higher_top_score_always_wins_regardless_of_coverage(self) -> None:
        """
        The coverage tie-break must never outrank a family with a
        genuinely higher top member score, no matter how many members
        the lower-scoring family has matched.
        """

        high_score_low_coverage = _definition("vision.describe", family="vision")
        low_score_members = tuple(
            _definition(f"ocr.step_{index}", family="ocr") for index in range(5)
        )

        scores = {"vision.describe": 0.9}
        scores.update({member.id: 0.2 for member in low_score_members})

        family_scores = rank_families(
            (high_score_low_coverage,) + low_score_members, scores=scores
        )

        assert family_scores["vision"] > family_scores["ocr"]

    def test_breaks_ties_between_equal_top_scores_by_coverage(self) -> None:
        single_match = _definition("weather.current", family="weather")
        multi_match_a = _definition("document.summarize", family="document")
        multi_match_b = _definition("document.search", family="document")

        scores = {
            "weather.current": 0.5,
            "document.summarize": 0.5,
            "document.search": 0.3,
        }

        family_scores = rank_families(
            (single_match, multi_match_a, multi_match_b), scores=scores
        )

        assert family_scores["document"] > family_scores["weather"]


class TestFallbackFamilyGrouping:
    def test_capabilities_with_no_declared_family_group_by_category(self) -> None:
        first = _definition("standalone.one", family=None)
        second = _definition("standalone.two", family=None)

        family_scores = rank_families(
            (first, second), scores={"standalone.one": 0.4, "standalone.two": 0.0}
        )

        assert len(family_scores) == 1
        assert next(iter(family_scores.values())) >= 0.4

    def test_family_with_no_scored_members_still_appears_with_zero_score(
        self,
    ) -> None:
        definition = _definition("unscored.capability", family="unscored")

        family_scores = rank_families((definition,), scores={})

        assert family_scores == {"unscored": 0.0}
