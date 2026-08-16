"""
Capability Catalog - Pipeline Stage adapters.

Each class here adapts one pure retrieval function (deterministic
filtering, lexical retrieval, semantic retrieval, family ranking,
capability retrieval, dynamic relevance cutoff, capability ranking,
budget selection) into the `PipelineStage` protocol
(`retrieval_context.py`), keeping `CapabilityCatalog.retrieve()` a
short, flat sequence of stages (see that module's docstring).

Adding a new retrieval stage means writing one more class here (or
wherever it naturally belongs) implementing `PipelineStage`, and
inserting it into `CapabilityCatalog`'s stage list -- no other file
needs to change, and no earlier stage needs to know it exists.

Pipeline order (see `capability_catalog.py`'s module docstring for the
full design rationale): Deterministic Filtering -> Lexical Retrieval
-> [Semantic Retrieval] -> Capability Family Retrieval -> Capability
Retrieval (combines own + family score) -> Dynamic Relevance Cutoff
(decides *how many* capabilities are relevant -- never a fixed count)
-> Capability Ranking (orders cutoff's survivors) -> Budget Safety
Ceiling (a safeguard against prompt explosion, not the retrieval
algorithm -- rarely triggers once cutoff has already done its job).

This module intentionally produces no log output. The Capability
Catalog does not log anything anywhere in its pipeline -- see
`docs/architecture/Request_Understanding.md` §4.9 for why.
"""

from __future__ import annotations

from .budget_selector import select_within_budget
from .capability_ranking import compute_combined_scores, rank_capabilities
from .deterministic_filter import filter_candidates
from .family_ranking import rank_families
from .lexical_retrieval import LexicalScorer, score_candidates
from .relevance_cutoff import apply_relevance_cutoff
from .retrieval_context import RetrievalContext
from .semantic_retrieval import SemanticScorer


class DeterministicFilteringStage:
    """
    Wraps `deterministic_filter.filter_candidates()`.
    """

    def run(self, context: RetrievalContext) -> RetrievalContext:
        context.candidates = filter_candidates(context.candidates)

        return context


class LexicalRetrievalStage:
    """
    Wraps `lexical_retrieval.score_candidates()`.
    """

    def __init__(self, *, scorer: LexicalScorer | None = None) -> None:
        self._scorer = scorer

    def run(self, context: RetrievalContext) -> RetrievalContext:
        context.scores = score_candidates(
            context.candidates, text=context.text, scorer=self._scorer
        )

        return context


class SemanticRetrievalStage:
    """
    Wraps a `SemanticScorer` and blends its output into
    `context.scores`. Only ever inserted into the pipeline when a
    `SemanticScorer` was actually supplied to `CapabilityCatalog` --
    see that class's docstring.
    """

    def __init__(self, *, scorer: SemanticScorer) -> None:
        self._scorer = scorer

    def run(self, context: RetrievalContext) -> RetrievalContext:
        semantic_scores = self._scorer.score(context.candidates, text=context.text)

        context.scores = {
            definition.id: context.scores.get(definition.id, 0.0)
            + semantic_scores.get(definition.id, 0.0)
            for definition in context.candidates
        }

        return context


class CapabilityFamilyRetrievalStage:
    """
    Wraps `family_ranking.rank_families()`. Named "Capability Family
    Retrieval" in the pipeline (see `capability_catalog.py`) since its
    output is what Capability Retrieval and Dynamic Relevance Cutoff
    use to decide relevance, not merely a final-order tie-break.
    """

    def run(self, context: RetrievalContext) -> RetrievalContext:
        context.family_scores = rank_families(
            context.candidates, scores=context.scores
        )

        return context


class CapabilityRetrievalStage:
    """
    Wraps `capability_ranking.compute_combined_scores()`: merges each
    candidate's own score with its family's boost into the single
    combined relevance score Dynamic Relevance Cutoff decides on.
    """

    def run(self, context: RetrievalContext) -> RetrievalContext:
        context.combined_scores = compute_combined_scores(
            context.candidates,
            scores=context.scores,
            family_scores=context.family_scores,
        )

        return context


class DynamicRelevanceCutoffStage:
    """
    Wraps `relevance_cutoff.apply_relevance_cutoff()`: this is the
    stage that decides *how many* capabilities are relevant to this
    turn -- never a fixed count -- based on the shape of the combined
    relevance scores `CapabilityRetrievalStage` just computed. Runs
    strictly before `CapabilityRankingStage` and
    `BudgetSelectionStage`; see `relevance_cutoff.py`'s module
    docstring for the retrieval strategy.
    """

    def run(self, context: RetrievalContext) -> RetrievalContext:
        result = apply_relevance_cutoff(
            context.candidates,
            combined_scores=context.combined_scores,
            family_scores=context.family_scores,
        )

        context.candidates = result.survivors

        return context


class CapabilityRankingStage:
    """
    Wraps `capability_ranking.rank_capabilities()`. Runs after Dynamic
    Relevance Cutoff -- it only orders capabilities cutoff already
    decided were relevant; it never decides relevance itself.
    """

    def run(self, context: RetrievalContext) -> RetrievalContext:
        context.candidates = rank_capabilities(
            context.candidates,
            combined_scores=context.combined_scores,
        )

        return context


class BudgetSelectionStage:
    """
    Wraps `budget_selector.select_within_budget()`.

    This is the Budget Safety Ceiling: a safeguard against prompt
    explosion for an unusually large genuinely-relevant set, never the
    mechanism that decides relevance -- that is Dynamic Relevance
    Cutoff's job, and runs strictly before this stage. In the common
    case, Dynamic Relevance Cutoff has already narrowed the roster
    well under `budget`, so this stage is a no-op.
    """

    def __init__(self, *, budget: int) -> None:
        self._budget = budget

    def run(self, context: RetrievalContext) -> RetrievalContext:
        context.candidates = select_within_budget(
            context.candidates, budget=self._budget
        )

        return context
