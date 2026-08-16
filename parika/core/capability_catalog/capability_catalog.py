"""
Capability Catalog.

A read-only retrieval/index layer built entirely on top of existing
runtime data (`CapabilityRegistry`). It is NOT another planner,
router, model, registry, resolver, or execution layer -- it never
executes anything, never chooses a provider or model, never invokes a
tool, and never replaces `CapabilityRegistry` or `CapabilityResolver`.
Its only job is: given the current turn's text and every currently
discoverable `CapabilityDefinition`, return a small, ranked subset of
*public leaf capabilities* worth advertising to the router/chat model
this turn.

Pipeline (see `docs/architecture/Request_Understanding.md` for the
full design):

    Candidates (from CapabilityRegistry)
        -> Deterministic Filtering      (deterministic_filter.py)
        -> Lexical Retrieval            (lexical_retrieval.py)
        -> [Semantic Retrieval]         (semantic_retrieval.py, optional)
        -> Capability Family Retrieval  (family_ranking.py)
        -> Capability Retrieval         (capability_ranking.compute_combined_scores())
        -> Dynamic Relevance Cutoff     (relevance_cutoff.py)
        -> Capability Ranking           (capability_ranking.rank_capabilities())
        -> Budget Safety Ceiling        (budget_selector.py)

This class is deliberately an **information retrieval engine followed
by a ranking engine**, not a sorter that only trims when a fixed count
is exceeded. Dynamic Relevance Cutoff -- not the budget -- is what
decides *how many* capabilities are genuinely relevant to this turn:
a narrow query (e.g. "what's the weather?") naturally survives cutoff
with only a couple of capabilities; a broad, genuinely multi-
capability request naturally survives with many more. The Budget
Safety Ceiling only ever protects against an unusually large
genuinely-relevant set turning into prompt explosion; it is not the
mechanism that determines relevance, and in the common case never
triggers because cutoff has already narrowed the roster.

Each stage's actual algorithm lives in its own pure, dependency-free
function module (listed above); `stages.py` adapts each one into the
`PipelineStage` protocol (`retrieval_context.py`) -- a fixed sequence
this class assembles once, in `_build_stages()`, and simply iterates
over in `retrieve()`. This keeps `CapabilityCatalog` itself a short,
flat sequencer: a future built-in retrieval stage is added by writing
one `PipelineStage` and inserting it into `_build_stages()`; a caller-
supplied stage can be added via `extra_stages` (see `__init__()`)
without editing this file at all. Neither path ever needs to grow
`retrieve()`'s own logic. Capability Families are used internally,
during retrieval and ranking, and are never returned -- the Catalog
always returns leaf capabilities.

This package produces no log output. Every stage is a pure function
of its inputs with no side effects -- see `docs/architecture/
Request_Understanding.md` §4.9 for why observability logging was
deliberately removed after development.
"""

from __future__ import annotations

from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)

from .lexical_retrieval import LexicalScorer
from .retrieval_context import PipelineStage, RetrievalContext
from .semantic_retrieval import SemanticScorer
from .stages import (
    BudgetSelectionStage,
    CapabilityFamilyRetrievalStage,
    CapabilityRankingStage,
    CapabilityRetrievalStage,
    DeterministicFilteringStage,
    DynamicRelevanceCutoffStage,
    LexicalRetrievalStage,
    SemanticRetrievalStage,
)

DEFAULT_BUDGET = 300
"""
Default maximum number of capabilities the Catalog will advertise for
a single turn -- a **safety ceiling**, not the retrieval algorithm
(see the module docstring). Dynamic Relevance Cutoff is what
ordinarily determines how many capabilities survive; this budget only
protects against an unusually large genuinely-relevant set (or, at
today's catalog size, a turn with no lexical signal at all, where
cutoff intentionally defers to the full roster) turning into prompt
explosion. Generous by design so it essentially never overrides
cutoff's own decision at PARIKA's current catalog size (raised from
150 to 300 after the Video Module's thirty additional TOOL
capabilities brought the enabled TOOL-category roster to 151 --
above the old ceiling -- which caused the Budget Safety Ceiling to
silently truncate one capability off the end of the *full-roster*
deferral case (a no-lexical-signal turn) for the first time; the
ceiling's job has always been "essentially never trigger at current
catalog size", not "cap the roster at a value that happens to match
whatever the catalog size was on the day it was picked", so this is a
ceiling adjustment, not a new mechanism or a per-Module special
case).
"""


class CapabilityCatalog:
    """
    Read-only retrieval layer over `CapabilityRegistry`.

    Owns exactly one responsibility: turning "every currently
    discoverable capability" plus "this turn's text" into "the small,
    ranked subset worth advertising" -- see the module docstring for
    the full pipeline and what this class explicitly does not do.
    """

    def __init__(
        self,
        *,
        budget: int = DEFAULT_BUDGET,
        lexical_scorer: LexicalScorer | None = None,
        semantic_scorer: SemanticScorer | None = None,
        extra_stages: tuple[PipelineStage, ...] = (),
    ) -> None:
        """
        Initialize the catalog.

        Args:
            budget:
                Maximum number of capabilities to return per
                `retrieve()` call. See `budget_selector.
                select_within_budget()` for the non-positive/
                unbounded semantics.

            lexical_scorer:
                Optional `LexicalScorer` override for the Lexical
                Retrieval stage; defaults to the field-weighted-IDF
                strategy described in `lexical_retrieval.py`'s module
                docstring.

            semantic_scorer:
                Optional `SemanticScorer` extension point (see
                `semantic_retrieval.py`). No implementation ships
                today; omitting this leaves semantic retrieval
                contributing nothing, exactly as before this
                parameter existed.

            extra_stages:
                Optional additional `PipelineStage`s, run in order
                after the Budget Safety Ceiling. This is the supported
                public extension point for a future retrieval stage
                that does not yet warrant its own constructor
                parameter (e.g. an experimental re-ranking pass) --
                see `retrieval_context.PipelineStage`. Defaults to
                `()`, leaving the fixed pipeline exactly as it was
                before this parameter existed.
        """

        self._stages: tuple[PipelineStage, ...] = self._build_stages(
            budget=budget,
            lexical_scorer=lexical_scorer,
            semantic_scorer=semantic_scorer,
            extra_stages=extra_stages,
        )

    @staticmethod
    def _build_stages(
        *,
        budget: int,
        lexical_scorer: LexicalScorer | None,
        semantic_scorer: SemanticScorer | None,
        extra_stages: tuple[PipelineStage, ...],
    ) -> tuple[PipelineStage, ...]:
        """
        Assemble the fixed pipeline stage sequence for this Catalog
        instance. Adding a future built-in stage (e.g. a re-ranking
        pass) means adding one more `PipelineStage` here --
        `retrieve()` itself never needs to change. Callers needing a
        stage without editing this file at all should use
        `extra_stages` instead (see `__init__()`'s docstring).
        """

        stages: list[PipelineStage] = [
            DeterministicFilteringStage(),
            LexicalRetrievalStage(scorer=lexical_scorer),
        ]

        if semantic_scorer is not None:
            stages.append(SemanticRetrievalStage(scorer=semantic_scorer))

        stages.extend(
            [
                CapabilityFamilyRetrievalStage(),
                CapabilityRetrievalStage(),
                DynamicRelevanceCutoffStage(),
                CapabilityRankingStage(),
                BudgetSelectionStage(budget=budget),
            ]
        )

        stages.extend(extra_stages)

        return tuple(stages)

    def retrieve(
        self,
        definitions: tuple[CapabilityDefinition, ...],
        *,
        text: str,
    ) -> tuple[CapabilityDefinition, ...]:
        """
        Run the full retrieval pipeline over `definitions`.

        Args:
            definitions:
                Every currently discoverable candidate capability,
                typically every enabled TOOL-category
                `CapabilityDefinition` returned by
                `CapabilityRegistry.find()`.

            text:
                The current turn's message text.

        Returns:
            A ranked, budget-limited tuple of leaf
            `CapabilityDefinition`s -- never a family, never a
            provider/model/tool selection.
        """

        context = RetrievalContext(
            text=text,
            original_definitions=definitions,
            candidates=definitions,
        )

        for stage in self._stages:
            context = stage.run(context)

        return context.candidates
