"""
Capability Catalog - Dynamic Relevance Cutoff stage.

This is the stage that actually makes the Capability Catalog behave
like an information-retrieval engine rather than a pure sorter: it
decides *how many* capabilities are genuinely relevant to this turn,
based entirely on the shape of relevance scores -- never a fixed
count, and never the Budget Safety Ceiling (`budget_selector.py`),
which only ever protects against an unusually large relevant set and
is applied strictly *after* this stage.

Provider-independent retrieval strategy chosen: a **two-level hybrid
of relative thresholding and score-gap ("elbow") detection** -- family
admission, then within-family member selection:

1. **Family admission** first decides *which topics are even in play*
   this turn, by applying the hybrid cutoff (below) to Capability
   Family Retrieval's per-family scores (`family_ranking.rank_families
   ()`). This is what correctly handles a genuinely broad,
   multi-domain request (e.g. "check the weather, convert some
   currency, and summarize this PDF"): each of Weather, Currency, and
   Document may have a different *natural* best score purely because
   their own discovery text differs in richness, so admitting families
   independently -- rather than comparing every individual capability
   only against the single globally-highest-scoring capability --
   avoids unfairly discarding an entire legitimately-relevant topic
   just because another topic happened to score higher in absolute
   terms.
2. **Within-family member selection** then applies the *same* hybrid
   cutoff a second time, scoped to each *admitted* family's own
   members and their own combined scores (`capability_ranking.
   compute_combined_scores()`) -- this is what lets a narrow, single-
   topic query (e.g. "what's the weather?") cut sharply down to just
   its 2-3 true matches within that one family, while a family that
   is itself broad (e.g. Document, if several of its members are all
   genuinely relevant to "summarize this PDF") keeps every one of its
   naturally-clustered members instead of being truncated to an
   arbitrary count.

The hybrid cutoff itself (`_hybrid_cutoff()`), applied identically at
both levels:

- **Relative threshold**: a candidate must score at least
  `_RELATIVE_THRESHOLD` of the *best candidate in its own comparison
  group* (all families, or one family's own members) to be considered
  relevant at all.
- **Score-gap detection**: sorted by descending score, the largest
  proportional drop between two consecutive candidates is treated as
  the "natural break" -- if that drop is large enough
  (`_GAP_SIGNIFICANCE_RATIO` of the group's best score), the cutoff
  moves up to sit exactly at that break.

These two rules are combined by taking the *stricter* (higher) of the
two cutoff scores, so neither rule alone can let through a candidate
the other rule would have excluded.

The critical exception -- and the reason this stage is safe to ship
without any capability-specific knowledge -- is when **no** candidate
scored above zero at all: this means the turn's text carried no
lexical (or semantic) signal whatsoever, not that every capability is
equally irrelevant. In that case cutoff is skipped entirely and every
deterministically-filtered candidate survives, deferring to the
model's own tool-calling reasoning exactly as PARIKA's Automatic
Capability Discovery has always done for an ambiguous/generic turn
(see `docs/architecture/Request_Understanding.md` §4).
"""

from __future__ import annotations

from dataclasses import dataclass

from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)

from .capability_family import resolve_family_ids

_RELATIVE_THRESHOLD = 0.5
"""
A candidate must score at least this fraction of its comparison
group's best score to survive, regardless of any gap found. Kept as
the "floor" half of the hybrid strategy -- see the module docstring.
Used for the within-family member-selection level, where the question
is "which of this *already-plausible* topic's own capabilities are
genuinely relevant" -- deliberately stricter than
`_FAMILY_ADMISSION_RELATIVE_THRESHOLD` below.
"""

_FAMILY_ADMISSION_RELATIVE_THRESHOLD = 0.2
"""
The relative threshold used at the family-admission level instead of
`_RELATIVE_THRESHOLD`, deliberately more lenient. Family admission only
answers "is this topic even plausibly in play this turn", not "is this
the single most relevant topic" -- a genuinely multi-domain request
(e.g. "check the weather, convert some currency, and summarize this
PDF") legitimately has topics whose own best possible score differs
purely because their discovery text differs in richness, not because
one topic is inherently less relevant than another. Requiring each
topic to reach half of the *globally* highest-scoring topic (as
`_RELATIVE_THRESHOLD` would) would unfairly discard weaker-but-real
topics; this lower bar only filters out topics with essentially no
signal at all, leaving within-family selection (which does use the
stricter threshold) to decide which of that topic's own capabilities
are worth advertising.
"""

_GAP_SIGNIFICANCE_RATIO = 0.25
"""
The minimum proportional drop (relative to the comparison group's best
score) between two consecutively ranked candidates for that drop to be
treated as a "natural break", moving the cutoff up to sit at the break
instead of at the relative threshold. See the module docstring.
Applied identically at both levels.
"""


@dataclass(frozen=True, slots=True, kw_only=True)
class RelevanceCutoffResult:
    """
    Outcome of one Dynamic Relevance Cutoff decision: exactly which
    candidates survived, which were discarded, and why -- useful for
    tests and any future diagnostic tooling, even though the
    Capability Catalog itself does not log any of it (see
    `docs/architecture/Request_Understanding.md` §4.9).
    """

    survivors: tuple[CapabilityDefinition, ...]
    discarded: tuple[CapabilityDefinition, ...]
    best_score: float
    cutoff_score: float
    reason: str


def _hybrid_cutoff(
    ids: list[str],
    scores: dict[str, float],
    *,
    relative_threshold: float = _RELATIVE_THRESHOLD,
    use_gap_detection: bool = True,
) -> tuple[frozenset[str], float]:
    """
    Apply the relative-threshold (+ optional score-gap) hybrid cutoff
    to one comparison group (either every family, or one family's own
    members) and return which ids survive plus the effective cutoff
    score. Shared by both cutoff levels -- see the module docstring --
    with `relative_threshold` letting each level use its own bar
    (`_RELATIVE_THRESHOLD` within a family,
    `_FAMILY_ADMISSION_RELATIVE_THRESHOLD` across families).

    `use_gap_detection=False` (used for family admission -- see
    `apply_relevance_cutoff()`) disables the score-gap half of the
    hybrid, keeping only the relative threshold: gap/"elbow" detection
    answers "where does the single dominant cluster end", which is
    the right question *within* one already-admitted topic, but the
    wrong one *across* topics -- a genuinely multi-domain request's
    weaker-but-real topics should not be discarded merely because one
    topic happens to score much higher in absolute terms.

    Every id in `ids` with a score of exactly 0.0 is guaranteed to be
    excluded by this function whenever at least one id in the group
    scored above zero (the cutoff score is always > 0.0 in that case);
    callers are responsible for the "no signal at all in this group"
    fallback (score every id 0.0 for the whole group), since that
    decision differs by comparison level (see `apply_relevance_cutoff
    ()`).
    """

    best = max((scores.get(i, 0.0) for i in ids), default=0.0)

    if best <= 0.0:
        return frozenset(ids), 0.0

    relative_cutoff = best * relative_threshold
    cutoff = relative_cutoff

    if use_gap_detection:
        ranked = sorted(ids, key=lambda i: -scores.get(i, 0.0))
        minimum_gap = best * _GAP_SIGNIFICANCE_RATIO

        largest_gap = 0.0
        largest_gap_score = relative_cutoff

        for current, following in zip(ranked, ranked[1:]):
            gap = scores.get(current, 0.0) - scores.get(following, 0.0)

            if gap > largest_gap:
                largest_gap = gap
                largest_gap_score = scores.get(current, 0.0)

        gap_cutoff = (
            largest_gap_score if largest_gap >= minimum_gap else relative_cutoff
        )
        cutoff = max(relative_cutoff, gap_cutoff)

    survivors = frozenset(i for i in ids if scores.get(i, 0.0) >= cutoff)

    return survivors, cutoff


def apply_relevance_cutoff(
    definitions: tuple[CapabilityDefinition, ...],
    *,
    combined_scores: dict[str, float],
    family_scores: dict[str, float],
) -> RelevanceCutoffResult:
    """
    Determine which candidates are genuinely relevant to this turn.

    Args:
        definitions:
            Candidate capabilities (post deterministic filtering).

        combined_scores:
            Each candidate's combined relevance score (own score +
            family boost; see `capability_ranking.
            compute_combined_scores()`), keyed by capability id.

        family_scores:
            Each retrieval family's rank score, keyed by family id
            (see `family_ranking.rank_families()`).

    Returns:
        A `RelevanceCutoffResult` describing exactly which candidates
        survived, which were discarded, and why.
    """

    best_score = max(
        (combined_scores.get(d.id, 0.0) for d in definitions), default=0.0
    )

    if best_score <= 0.0:
        return RelevanceCutoffResult(
            survivors=(),
            discarded=definitions,
            best_score=0.0,
            cutoff_score=0.0,
            reason=(
                "no capability scored above zero for this turn's text "
                "(no lexical/semantic signal found); advertising zero "
                "tools for no-signal conversational requests"
            ),
        )

    family_ids = resolve_family_ids(definitions)

    admitted_family_ids, family_cutoff_score = _hybrid_cutoff(
        list(family_scores.keys()),
        family_scores,
        relative_threshold=_FAMILY_ADMISSION_RELATIVE_THRESHOLD,
        use_gap_detection=False,
    )

    by_family: dict[str, list[CapabilityDefinition]] = {}

    for definition in definitions:
        by_family.setdefault(family_ids[definition.id], []).append(definition)

    survivors: list[CapabilityDefinition] = []
    discarded: list[CapabilityDefinition] = []
    admitted_family_count = 0

    for family_id, members in by_family.items():
        if family_id not in admitted_family_ids:
            discarded.extend(members)
            continue

        admitted_family_count += 1

        member_survivor_ids, _ = _hybrid_cutoff(
            [member.id for member in members], combined_scores
        )

        for member in members:
            (survivors if member.id in member_survivor_ids else discarded).append(
                member
            )

    def _by_descending_score(definition: CapabilityDefinition) -> tuple[float, str]:
        return (-combined_scores.get(definition.id, 0.0), definition.id)

    survivors_sorted = tuple(sorted(survivors, key=_by_descending_score))
    discarded_sorted = tuple(sorted(discarded, key=_by_descending_score))

    effective_cutoff_score = (
        min(combined_scores.get(d.id, 0.0) for d in survivors_sorted)
        if survivors_sorted
        else best_score
    )

    reason = (
        f"{admitted_family_count}/{len(family_scores)} capability "
        f"family(ies) admitted (family-level cutoff "
        f"{family_cutoff_score:.2f} of best family score "
        f"{max(family_scores.values(), default=0.0):.2f}); within each "
        f"admitted family, members kept via the same relative "
        f"threshold ({_RELATIVE_THRESHOLD:.0%} of that family's best "
        f"member) and score-gap hybrid; effective overall cutoff "
        f"{effective_cutoff_score:.2f}"
    )

    return RelevanceCutoffResult(
        survivors=survivors_sorted,
        discarded=discarded_sorted,
        best_score=best_score,
        cutoff_score=effective_cutoff_score,
        reason=reason,
    )
