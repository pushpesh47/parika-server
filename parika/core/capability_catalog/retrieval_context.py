"""
Capability Catalog - Retrieval Pipeline Context.

Defines the mutable state threaded through the Capability Catalog's
pipeline stages (see `stages.py`) and the `PipelineStage` protocol
every stage implements. Introduced so a future retrieval stage (e.g.
a re-ranking pass, or a stage consuming a new metadata field) can be
added by writing one small `PipelineStage` and inserting it into
`CapabilityCatalog`'s stage list -- without editing `CapabilityCatalog
.retrieve()` itself or any earlier stage, and without `CapabilityCatalog`
growing into a large monolithic orchestrator as stages are added.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)


@dataclass
class RetrievalContext:
    """
    Mutable state threaded through the retrieval pipeline.

    Each `PipelineStage` reads whatever fields it needs and returns
    the updated context -- typically the same instance, mutated in
    place. `text` and `original_definitions` are the pipeline's
    inputs and must never be mutated by a stage; `candidates`,
    `scores`, and `family_scores` are the pipeline's working state,
    refined stage by stage.
    """

    text: str

    original_definitions: tuple[CapabilityDefinition, ...]
    """
    Every candidate capability as originally received by
    `CapabilityCatalog.retrieve()`, before any stage ran. Kept
    unmodified for any stage that needs to compare against the
    starting roster.
    """

    candidates: tuple[CapabilityDefinition, ...]
    """
    The current working set of capabilities, narrowed and/or reordered
    by each stage in turn. This is what the final stage's output
    becomes `CapabilityCatalog.retrieve()`'s return value.
    """

    scores: dict[str, float] = field(default_factory=dict)
    """
    Per-capability relevance scores, keyed by capability id, as
    accumulated by retrieval stages (lexical, and optionally
    semantic).
    """

    family_scores: dict[str, float] = field(default_factory=dict)
    """
    Per-family rank scores, keyed by family id, as computed by the
    Capability Family Ranking stage.
    """

    combined_scores: dict[str, float] = field(default_factory=dict)
    """
    Per-capability combined relevance score (own score + family
    boost), keyed by capability id, as computed by the Capability
    Retrieval stage (`capability_ranking.compute_combined_scores()`).
    This is the single number Dynamic Relevance Cutoff and the final
    Capability Ranking stage both reason about.
    """


class PipelineStage(Protocol):
    """
    One stage of the Capability Catalog's retrieval pipeline.

    A stage is a pure transformation of `RetrievalContext` -- it must
    never execute anything, choose a provider/model, or invoke a tool,
    and (see `stages.py`) must not log anything: the Capability
    Catalog produces no log output.
    """

    def run(self, context: RetrievalContext) -> RetrievalContext:
        """
        Apply this stage to `context` and return the updated context.
        """

        ...
