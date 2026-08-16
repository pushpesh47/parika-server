"""
Capability Catalog - Capability Family Ranking stage.

Groups already-scored candidate capabilities into their retrieval
Families (see `capability_family.py`) and ranks the families by the
best lexical/semantic score any of their member capabilities
achieved. This lets the pipeline reason about "which families are
even relevant" before ranking individual capabilities within them --
purely an internal ranking aid; families themselves are never
returned to callers.

Design note (max-pooling vs. averaging): a family's score is anchored
on its single best-scoring member, not an average. Averaging would let
a large family with many weakly/un-related members dilute a genuinely
strong match from one of its siblings -- exactly backwards, since one
strongly relevant capability is real evidence the whole family is
relevant to this turn, while many irrelevant siblings are not evidence
against it. Max-pooling is the standard choice for this kind of
coarse-to-fine "cluster, then re-rank within the best clusters"
retrieval and is kept as the primary signal here.

A small secondary signal is added on top for tie-breaking only: a
bonus for the number of *distinct* members that matched at all (a
stronger topical signal than a single incidental match), strictly as
a tie-breaker among families that already share the same top member
score. It is deliberately based on the absolute matched-member count,
not on a fraction of family size -- a fraction would reward a
one-capability family that happens to match exactly as much as a
ten-capability family where every member matched, which is backwards.
The bonus is also capped and weighted far below a single point of raw
score, so it can never let a family with a genuinely lower top score
outrank one with a genuinely higher top score.
"""

from __future__ import annotations

from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)

from .capability_family import resolve_family_ids

_MATCH_COUNT_TIE_BREAK_WEIGHT = 0.01
"""
Weight applied per distinct matched member, up to
`_MATCH_COUNT_TIE_BREAK_CAP` members, on top of a family's best
member score. Kept deliberately small and capped -- see the module
docstring's design note -- so it only ever breaks ties between
families whose top member score is otherwise equal.
"""

_MATCH_COUNT_TIE_BREAK_CAP = 5
"""
Maximum number of matched members counted toward the tie-break bonus,
so a very large family cannot accumulate an unbounded bonus purely by
size.
"""


def rank_families(
    definitions: tuple[CapabilityDefinition, ...],
    *,
    scores: dict[str, float],
) -> dict[str, float]:
    """
    Compute each retrieval family's rank score.

    Args:
        definitions:
            Candidate capabilities (post deterministic filtering).

        scores:
            Per-capability relevance scores, keyed by capability id
            (typically the merged lexical + semantic scores).

    Returns:
        A mapping of family id to that family's rank score: its best
        member score, plus a small matched-member-count tie-break
        (see the module docstring). A family with no scored members
        yet still appears, with a score of 0.0, so it is never
        silently dropped.
    """

    family_ids = resolve_family_ids(definitions)

    best_member_score: dict[str, float] = {}
    matched_member_count: dict[str, int] = {}

    for definition in definitions:
        family_id = family_ids[definition.id]
        member_score = scores.get(definition.id, 0.0)

        best_member_score[family_id] = max(
            best_member_score.get(family_id, 0.0), member_score
        )

        if member_score > 0.0:
            matched_member_count[family_id] = (
                matched_member_count.get(family_id, 0) + 1
            )

    return {
        family_id: best_score
        + (
            min(
                matched_member_count.get(family_id, 0),
                _MATCH_COUNT_TIE_BREAK_CAP,
            )
            * _MATCH_COUNT_TIE_BREAK_WEIGHT
        )
        for family_id, best_score in best_member_score.items()
    }
