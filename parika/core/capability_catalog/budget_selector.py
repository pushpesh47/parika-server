"""
Capability Catalog - Budget Safety Ceiling stage.

The final pipeline stage: truncates an already fully ranked tuple of
*already-relevant* candidate capabilities (Dynamic Relevance Cutoff's
survivors -- see `relevance_cutoff.py`) to at most `budget` entries.
This is a safeguard against prompt explosion for an unusually large
genuinely-relevant set, never the mechanism that decides relevance --
that is Dynamic Relevance Cutoff's job, and it always runs first. When
the number of candidates is within budget (the common case, since
cutoff has typically already narrowed the roster well under it), this
stage is a no-op and every candidate survives -- it never trims down
to a fixed count on its own.
"""

from __future__ import annotations

from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)


def select_within_budget(
    ranked_definitions: tuple[CapabilityDefinition, ...],
    *,
    budget: int,
) -> tuple[CapabilityDefinition, ...]:
    """
    Select the top `budget` capabilities from an already ranked tuple.

    Args:
        ranked_definitions:
            Capabilities ordered from most to least relevant (see
            `capability_ranking.rank_capabilities()`).

        budget:
            Maximum number of capabilities to advertise this turn. A
            non-positive budget is treated as "unbounded" rather than
            "advertise nothing", since a misconfigured budget must
            never silently disable every capability.

    Returns:
        `ranked_definitions[:budget]`, or all of `ranked_definitions`
        when `budget` is non-positive or already satisfied.
    """

    if budget <= 0:
        return ranked_definitions

    return ranked_definitions[:budget]
