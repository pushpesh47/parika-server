"""
Capability Catalog - Semantic Retrieval extension point.

Semantic (embedding-based) retrieval is intentionally NOT implemented
yet -- this module exists only to reserve the extension point so it
can be plugged into the pipeline later without changing
`CapabilityCatalog`'s public API.

`CapabilityCatalog` accepts an optional `SemanticScorer` and, when one
is supplied, blends its scores with lexical retrieval scores in
`capability_ranking.py` exactly like any other score source. When none
is supplied (the default today), semantic retrieval simply contributes
nothing -- the pipeline behaves exactly as if this module did not
exist.
"""

from __future__ import annotations

from typing import Protocol

from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)


class SemanticScorer(Protocol):
    """
    Future extension point for embedding/semantic relevance scoring.

    A real implementation would typically embed `text` and each
    candidate's discovery text once (e.g. via a Provider Driver) and
    return a cosine-similarity-derived score. No such implementation
    exists yet in PARIKA; this `Protocol` only fixes the shape a
    future implementation must have so it can be adopted without
    touching `CapabilityCatalog` or any of its callers.

    Score contract: like every `LexicalScorer` (see
    `lexical_retrieval.py`), a `SemanticScorer` must return scores in
    the same canonical `[0.0, 1.0]` range. `CapabilityCatalog`
    combines lexical and semantic scores by simple addition (see
    `stages.SemanticRetrievalStage`); keeping both sources in the same
    bounded range is what makes that combination meaningful without
    a separate renormalization step.
    """

    def score(
        self,
        definitions: tuple[CapabilityDefinition, ...],
        *,
        text: str,
    ) -> dict[str, float]:
        """
        Return a mapping of capability id to semantic relevance score
        for `text`, in `[0.0, 1.0]`.
        """

        ...
