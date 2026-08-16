"""
Unit tests for `parika.core.capability_catalog.relevance_cutoff`.

Every test definition below declares no explicit `family` and no
`tags`, so all fall back to the same single retrieval family
(`family_ranking.family_id_for()`'s category-derived fallback). This
means, for these tests, Dynamic Relevance Cutoff's family-admission
level trivially admits that one family, and the within-family hybrid
cutoff is what each test actually exercises -- `test_capability_family.py`
and `test_capability_catalog.py`'s multi-family scenarios cover family
admission itself.
"""

from __future__ import annotations

from parika.core.capability_catalog.family_ranking import rank_families
from parika.core.capability_catalog.relevance_cutoff import (
    apply_relevance_cutoff,
)
from parika.core.capability_registry.capability_category import (
    CapabilityCategory,
)
from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)


def _definition(capability_id: str) -> CapabilityDefinition:
    return CapabilityDefinition(
        id=capability_id,
        name=capability_id,
        description="",
        category=CapabilityCategory.TOOL,
    )


def _cutoff(
    definitions: tuple[CapabilityDefinition, ...], scores: dict[str, float]
):
    """
    Convenience wrapper: derives `family_scores` from `scores` via the
    real `rank_families()` (all test definitions share one fallback
    family), then calls `apply_relevance_cutoff()`.
    """

    family_scores = rank_families(definitions, scores=scores)

    return apply_relevance_cutoff(
        definitions, combined_scores=scores, family_scores=family_scores
    )


class TestNoSignalDefersToFullRoster:
    def test_every_candidate_survives_when_nothing_scored_above_zero(self) -> None:
        """
        "No candidate scored above zero" means "we have no signal to
        judge relevance by", not "everything is equally irrelevant" --
        cutoff must defer to the full roster rather than guess, exactly
        like PARIKA's existing Automatic Capability Discovery does for
        an ambiguous/generic turn.
        """

        definitions = (_definition("a"), _definition("b"), _definition("c"))

        result = _cutoff(definitions, scores={})

        assert result.survivors == definitions
        assert result.discarded == ()
        assert result.best_score == 0.0
        assert "no capability scored above zero" in result.reason


class TestRelativeThreshold:
    def test_discards_candidates_scoring_well_below_the_best_candidate(
        self,
    ) -> None:
        strong = _definition("weather.current")
        weak = _definition("filesystem.mkdir")

        result = _cutoff(
            (strong, weak),
            {"weather.current": 0.9, "filesystem.mkdir": 0.1},
        )

        assert result.survivors == (strong,)
        assert result.discarded == (weak,)
        assert result.best_score == 0.9

    def test_keeps_candidates_scoring_close_to_the_best_candidate(self) -> None:
        first = _definition("weather.current")
        second = _definition("weather.forecast")

        result = _cutoff(
            (first, second),
            {"weather.current": 0.9, "weather.forecast": 0.7},
        )

        assert set(d.id for d in result.survivors) == {
            "weather.current",
            "weather.forecast",
        }


class TestZeroScoringCandidatesAreAlwaysDiscardedOnceThereIsSignal:
    def test_zero_score_candidate_never_survives_alongside_a_real_match(
        self,
    ) -> None:
        matched = _definition("weather.current")
        unrelated = _definition("filesystem.mkdir")

        result = _cutoff((matched, unrelated), {"weather.current": 0.3})

        assert result.survivors == (matched,)
        assert result.discarded == (unrelated,)


class TestGapDetection:
    def test_a_large_gap_cuts_off_a_long_tail_of_weak_matches(self) -> None:
        dominant = _definition("weather.current")
        weak_tail = tuple(_definition(f"weak.{i}") for i in range(20))

        scores = {"weather.current": 0.9}
        scores.update({d.id: 0.05 for d in weak_tail})

        result = _cutoff((dominant,) + weak_tail, scores)

        assert result.survivors == (dominant,)
        assert len(result.discarded) == 20

    def test_a_genuinely_broad_relevant_cluster_is_not_truncated_to_a_count(
        self,
    ) -> None:
        """
        A broad, multi-capability request (e.g. "summarize this PDF")
        legitimately touches several similarly-relevant capabilities.
        Dynamic Relevance Cutoff must keep all of them rather than
        truncating to an arbitrary number, as long as they form one
        natural cluster with no significant internal gap.
        """

        cluster = (
            _definition("document.summarize"),
            _definition("document.read_pdf"),
            _definition("document.extract_text"),
            _definition("ocr.extract_text"),
        )

        scores = {
            "document.summarize": 0.9,
            "document.read_pdf": 0.85,
            "document.extract_text": 0.8,
            "ocr.extract_text": 0.75,
        }

        result = _cutoff(cluster, scores)

        assert len(result.survivors) == 4
        assert result.discarded == ()


class TestResultOrdering:
    def test_survivors_are_returned_sorted_by_descending_score(self) -> None:
        low = _definition("low")
        high = _definition("high")

        result = _cutoff((low, high), {"low": 0.75, "high": 0.9})

        assert [d.id for d in result.survivors] == ["high", "low"]


class TestMultiFamilyAdmission:
    """
    Distinct retrieval families (via `tags`) are admitted or discarded
    independently, based on each family's *own* best score relative to
    the *overall* best family score -- not by comparing every
    individual capability only against the single globally-highest-
    scoring capability. This is what correctly handles a genuinely
    broad, multi-domain request touching several topics whose natural
    score scales differ.
    """

    @staticmethod
    def _tagged(capability_id: str, *, tag: str) -> CapabilityDefinition:
        return CapabilityDefinition(
            id=capability_id,
            name=capability_id,
            description="",
            category=CapabilityCategory.TOOL,
            tags=frozenset({tag}),
        )

    def test_a_weakly_admitted_family_still_keeps_its_own_best_member(
        self,
    ) -> None:
        weather = self._tagged("weather.current", tag="weather")
        currency = self._tagged("currency.convert", tag="currency")

        scores = {"weather.current": 0.9, "currency.convert": 0.35}

        result = _cutoff((weather, currency), scores)

        assert set(d.id for d in result.survivors) == {
            "weather.current",
            "currency.convert",
        }

    def test_a_family_with_no_real_signal_is_fully_discarded(self) -> None:
        weather = self._tagged("weather.current", tag="weather")
        unrelated = self._tagged("filesystem.mkdir", tag="filesystem")

        scores = {"weather.current": 0.9, "filesystem.mkdir": 0.01}

        result = _cutoff((weather, unrelated), scores)

        assert result.survivors == (weather,)
        assert result.discarded == (unrelated,)
