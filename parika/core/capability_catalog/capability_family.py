"""
Capability family model.

A Capability Family is a retrieval-time grouping of related leaf
capabilities (e.g. "document", "vision", "ocr", "coding"). Families
exist ONLY to make retrieval and ranking scale as the number of
registered capabilities grows -- they are never executable, never a
Module, never a Provider, and never advertised to a router/chat model
in place of a leaf capability. The router always receives leaf
`CapabilityDefinition`s; families are discarded once retrieval is
done.

Families are a retrieval boundary, distinct from Modules, which are
implementation/ownership boundaries. A single Module may own
capabilities from several families, and a family may be served by
capabilities owned by several Modules -- the two concepts are
intentionally not equated (see `docs/architecture/
Request_Understanding.md`).
"""

from __future__ import annotations

from dataclasses import dataclass

from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)

_FALLBACK_FAMILY_PREFIX = "category:"
"""
Prefix used to derive a fallback family identifier from a capability's
`category` when it declares no explicit `family`. Keeping this
distinct from any real family id avoids accidental collisions.
"""


@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityFamily:
    """
    Immutable, read-only retrieval grouping of leaf capabilities.

    A `CapabilityFamily` is not registered anywhere and not stored by
    `CapabilityRegistry` -- it is assembled on demand by the
    Capability Catalog from the `family` (or category-derived
    fallback) field of currently discoverable `CapabilityDefinition`s.
    """

    id: str
    capability_ids: tuple[str, ...]


def family_id_for(
    *,
    family: str | None,
    category: str,
    tags: frozenset[str] = frozenset(),
    tag_frequency: dict[str, int] | None = None,
) -> str:
    """
    Resolve the retrieval family identifier for a single capability.

    Args:
        family:
            The capability's own declared `family`, if any.

        category:
            The capability's `category` value (used as the final
            fallback grouping when no explicit `family` is declared
            and the capability has no `tags` either).

        tags:
            The capability's own `tags` (already populated by most
            Modules today -- e.g. every `coding.*` capability shares
            `{"coding", "development"}`), used as the second fallback
            grouping when no explicit `family` is declared. This
            reuses existing, already-populated data rather than
            requiring every Module to additionally populate the newer
            `family` field before family-based retrieval becomes
            useful.

        tag_frequency:
            Optional mapping of tag to how many candidates in the
            current retrieval batch carry it (see
            `resolve_family_ids()`). When supplied, the *least
            frequent* (most specific) tag is preferred over a broadly
            shared one -- e.g. an OCR capability tagged
            `{"ocr", "vision", "image"}` resolves to `"ocr"` rather
            than the more generic `"vision"`/`"image"` it happens to
            share with the Vision Module, and a Weather capability
            tagged `{"weather", "network"}` resolves to `"weather"`
            rather than the generic `"network"` it happens to share
            with several unrelated domains (Currency, News, Web
            Search). Omitting this falls back to the alphabetically
            first tag, purely for deterministic behavior when corpus-
            wide frequency is unavailable (e.g. direct unit tests of
            this function in isolation) -- `resolve_family_ids()` is
            the supported entry point for real retrieval.

    Returns:
        `family` if non-empty; otherwise the most specific applicable
        tag, if any tags are set; otherwise a stable fallback
        identifier derived from `category`.
    """

    if family:
        return family

    if tags:
        if tag_frequency is not None:
            return min(tags, key=lambda tag: (tag_frequency.get(tag, 0), tag))

        return min(tags)

    return f"{_FALLBACK_FAMILY_PREFIX}{category}"


def resolve_family_ids(
    definitions: tuple[CapabilityDefinition, ...],
) -> dict[str, str]:
    """
    Resolve the retrieval family identifier for every capability in
    `definitions` at once, using each capability's own tags weighted
    by how specific they are *within this batch* (see `family_id_for
    ()`'s `tag_frequency` parameter for why this matters).

    This is the supported entry point for real retrieval stages
    (`family_ranking.py`, `capability_ranking.py`, `relevance_cutoff
    .py`); `family_id_for()` remains available directly for isolated
    single-capability resolution (e.g. tests, or a capability whose
    `family` is already explicitly declared).

    Args:
        definitions:
            Every candidate capability in the current retrieval batch
            (post deterministic filtering) -- tag frequency is scoped
            to exactly this set, never the full `CapabilityRegistry`,
            so family resolution adapts to whatever is actually being
            considered this turn.

    Returns:
        A mapping of capability id to resolved family id.
    """

    tag_frequency: dict[str, int] = {}

    for definition in definitions:
        for tag in definition.tags:
            tag_frequency[tag] = tag_frequency.get(tag, 0) + 1

    return {
        definition.id: family_id_for(
            family=definition.family,
            category=definition.category.value,
            tags=definition.tags,
            tag_frequency=tag_frequency,
        )
        for definition in definitions
    }
