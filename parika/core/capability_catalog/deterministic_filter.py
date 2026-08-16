"""
Capability Catalog - Deterministic Filtering stage.

The first, purely deterministic stage of the retrieval pipeline: it
removes capabilities that cannot possibly be selected for this turn,
before any lexical or ranking logic runs. Nothing here is
probabilistic or model-driven -- every check is a plain boolean
predicate over a `CapabilityDefinition`'s own fields/metadata.

This stage never mentions a specific capability id by name (Capability
Independence, see `parika/interfaces/ai_context/__init__.py`); every
check reads a generic field or metadata key that any capability may
opt into.
"""

from __future__ import annotations

from collections.abc import Iterable

from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)


def _is_possible(definition: CapabilityDefinition) -> bool:
    """
    Determine whether `definition` can possibly be advertised, based
    solely on its own deterministic fields/metadata:

    - `enabled`: disabled capabilities are never advertised.
    - `public`: internal-only capabilities are never advertised.
    - `metadata["catalog_excluded"]`: an explicit, capability-owned
      opt-out (e.g. for a capability that is technically public but
      only ever meant to be invoked directly, never offered to a
      router model).

    Modality/artifact/runtime-state compatibility checks are
    intentionally left as capability-owned metadata predicates rather
    than hardcoded here -- see `metadata["compatibility_predicate"]`
    below -- since only the capability itself knows what it requires.
    """

    if not definition.enabled:
        return False

    if not definition.public:
        return False

    if definition.metadata.get("catalog_excluded"):
        return False

    compatibility_predicate = definition.metadata.get("compatibility_predicate")

    if compatibility_predicate is not None and not compatibility_predicate():
        return False

    return True


def filter_candidates(
    definitions: Iterable[CapabilityDefinition],
) -> tuple[CapabilityDefinition, ...]:
    """
    Remove capabilities that cannot possibly be selected.

    Args:
        definitions:
            Candidate capabilities, typically every enabled
            TOOL-category `CapabilityDefinition` already returned by
            `CapabilityRegistry.find()`.

    Returns:
        The subset of `definitions` that pass every deterministic
        check, in the same relative order.
    """

    return tuple(
        definition for definition in definitions if _is_possible(definition)
    )
