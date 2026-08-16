"""
PARIKA Core - Semantic Profile Resolution

Combines the two Semantic Enrichment evidence sources into the final,
canonical `ProviderModel.specializations` a model is discovered with.

Resolution order, deliberately simple (see `parika/core/semantics
/__init__.py`'s module docstring):

    1. Provider Metadata evidence (specialization tags a provider's
       own mapping code already derived from its raw metadata - e.g.
       `parika.providers.ollama.model_mapping.specializations_from_show()`),
       normalized through `vocabulary.normalize()`.
    2. Local Curated Override (`model_knowledge.get_override()`),
       which always wins: its `remove` set is subtracted, then its
       `add` set is unioned in.

Deliberately NOT implemented here, by design:

    - Confidence scoring or weighting between evidence sources.
    - Multi-source evidence ranking beyond "override always wins".
    - Runtime/learned semantic inference.
    - Automatic semantic discovery from usage data.
    - Community-contributed semantic packages.
    - Complex taxonomy traversal.

These may become future evidence sources or resolution refinements,
but nothing in this module depends on them existing, and adding one
later never requires changing `resolve_specializations()`'s signature
or this module's two-step resolution order.
"""

from __future__ import annotations

from collections.abc import Iterable

from . import model_knowledge, vocabulary


def resolve_specializations(
    model_id: str,
    provider_reported: Iterable[str],
) -> frozenset[str]:
    """
    Resolve a model's final, canonical `ProviderModel.specializations`.

    Args:
        model_id:
            The model's id, used to look up a Local Curated Override
            (see `model_knowledge.get_override()`).

        provider_reported:
            The specialization tags a Provider Metadata evidence
            source already derived from that provider's raw metadata
            (e.g. `specializations_from_show()`). May be empty when a
            provider reports no usable metadata at all.

    Returns:
        The final, canonical specialization set: Provider Metadata
        evidence, normalized, with any Local Curated Override applied
        on top (override always wins).
    """

    normalized = {vocabulary.normalize(value) for value in provider_reported}

    override = model_knowledge.get_override(model_id)

    if override is None:
        return frozenset(normalized)

    return frozenset((normalized - override.remove) | override.add)
