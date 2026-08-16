"""
Capability Catalog - Capability Retrieval and Capability Ranking
stages.

Two closely related, deliberately separate responsibilities live here:

- `compute_combined_scores()` ("Capability Retrieval"): merges each
  capability's own lexical/semantic score with its family's rank score
  (a small family-level boost so that a capability belonging to an
  overall more relevant family is preferred over an equally (un)scored
  capability from an unrelated family) into the single relevance
  number the rest of the pipeline reasons about. This runs *before*
  Dynamic Relevance Cutoff (`relevance_cutoff.py`), since cutoff must
  decide relevance using the fully combined signal, not lexical score
  alone.
- `rank_capabilities()` ("Capability Ranking"): produces the final,
  fully ordered tuple of *already-relevant* leaf capabilities (i.e.
  cutoff's survivors) from their combined scores, breaking ties
  deterministically by capability id so ranking is stable across runs.
  This runs *after* cutoff -- it only ever orders the capabilities
  cutoff already decided were relevant; it never decides relevance
  itself.

Families are used only to compute the combined score -- the final
return value is always a flat, ordered tuple of leaf
`CapabilityDefinition`s, never a family.
"""

from __future__ import annotations

from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)

from .capability_family import resolve_family_ids

_FAMILY_BOOST_WEIGHT = 0.1
"""
Small, fixed weight applied to a capability's family rank score when
computing its combined relevance score. Kept deliberately small so
that a capability's own lexical/semantic relevance always dominates;
the family boost only nudges otherwise similarly-scored capabilities
(and, by extension, Dynamic Relevance Cutoff's decisions about them).
"""


def compute_combined_scores(
    definitions: tuple[CapabilityDefinition, ...],
    *,
    scores: dict[str, float],
    family_scores: dict[str, float],
) -> dict[str, float]:
    """
    Combine each capability's own score with its family's boost.

    Args:
        definitions:
            Candidate capabilities (post deterministic filtering).

        scores:
            Per-capability relevance scores, keyed by capability id
            (typically the merged lexical + semantic scores).

        family_scores:
            Per-family rank scores, keyed by family id (see
            `family_ranking.rank_families()`).

    Returns:
        A mapping of capability id to combined relevance score --
        this is the single number Dynamic Relevance Cutoff and the
        final ranking both reason about from this point on.
    """

    family_ids = resolve_family_ids(definitions)
    combined: dict[str, float] = {}

    for definition in definitions:
        own_score = scores.get(definition.id, 0.0)
        family_id = family_ids[definition.id]
        family_score = family_scores.get(family_id, 0.0)

        combined[definition.id] = own_score + (
            family_score * _FAMILY_BOOST_WEIGHT
        )

    return combined


def rank_capabilities(
    definitions: tuple[CapabilityDefinition, ...],
    *,
    combined_scores: dict[str, float],
) -> tuple[CapabilityDefinition, ...]:
    """
    Order already-relevant candidate capabilities by combined
    relevance.

    Args:
        definitions:
            Candidate capabilities -- typically Dynamic Relevance
            Cutoff's survivors, though this function itself performs
            no filtering of its own.

        combined_scores:
            Each capability's combined relevance score, keyed by
            capability id (see `compute_combined_scores()`).

    Returns:
        `definitions` ordered from most to least relevant, ties
        broken deterministically by capability id.
    """

    def _rank_key(definition: CapabilityDefinition) -> tuple[float, str]:
        combined = combined_scores.get(definition.id, 0.0)

        # Negate the score so ascending sort yields descending rank;
        # capability id remains ascending for deterministic tie-breaks.
        return (-combined, definition.id)

    return tuple(sorted(definitions, key=_rank_key))
