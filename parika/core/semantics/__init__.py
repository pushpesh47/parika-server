"""
PARIKA Core - Semantics Package

Provides the Core-level Semantic Enrichment layer of the Model
Selection Framework: the step between Provider Discovery/Mechanical
Provider Metadata and `ProviderModel` that resolves a model's final,
canonical `ProviderModel.specializations` from whatever evidence is
available.

    Provider Discovery
        -> Mechanical Provider Metadata   (a provider package, e.g.
                                            parika/providers/ollama/model_mapping.py)
        -> Semantic Enrichment            (this package)
        -> ProviderModel
        -> Planner (unchanged)

Two evidence sources feed the resolution performed by
`resolve_specializations()`:

    1. Provider Metadata evidence - specialization tags a provider's
       own mapping/driver code already derived from that provider's
       raw metadata (e.g.
       `parika.providers.ollama.model_mapping.specializations_from_show()`).
       Provider-specific knowledge lives entirely in the provider
       package; this package never imports from `parika.providers.*`
       and has no opinion about any specific provider's API shape.

    2. Local Curated Override evidence (`model_knowledge.py`) -
       PARIKA's own hand-curated corrections for specific models
       where Provider Metadata evidence is known to be wrong or
       incomplete (e.g. `"glm-ocr"` incorrectly inferring
       `"general_chat"` from Ollama's generic `"completion"`
       capability).

Resolution (`resolution.py`) is deliberately simple: Provider Metadata
evidence first, then the Local Curated Override always wins - nothing
more. No confidence scoring, no multi-source evidence ranking, no
runtime learning; see `resolution.py`'s module docstring for the full
list of things deliberately not implemented here.

`vocabulary.py` owns only canonical semantic concept ids, aliases, and
normalization - it has no opinion about providers, models, or
overrides at all.

`model_knowledge.py` also owns a second, deliberately separate
concept: PARIKA Model Knowledge (`ModelKnowledgeEntry`/
`get_model_knowledge()`) -- PARIKA's own observed knowledge about a
model's real-world strengths (obtained through benchmarking, manual
testing, or evaluation), never provider metadata, and never fed into
`ProviderModel`/filtering/scoring. It exists solely to be surfaced,
clearly labeled as PARIKA's own knowledge, inside the worker model
inventory an AI-assisted routing model reasons over (see
`parika/interfaces/ai_context/worker_inventory.py`). See
`model_knowledge.py`'s own module docstring for the full rationale.

This package is Core-level (not provider-level) because Semantic
Enrichment is a generic, provider-independent responsibility, not
because it has many consumers today - see `PARIKA_Core_Coding
_Standards.md`'s responsibility-separation guidance. Only
`ProviderModel.specializations` is governed by this package; every
other `ProviderModel` field (`capabilities`, `execution_features`,
`supported_modalities`, `resource_requirements`) is unaffected and
continues to be populated exactly as before.
"""

from __future__ import annotations

from .model_knowledge import (
    ModelKnowledgeEntry,
    SpecializationOverride,
    get_model_knowledge,
    get_override,
)
from .resolution import resolve_specializations
from .vocabulary import CANONICAL_CONCEPTS, normalize

__all__ = [
    "CANONICAL_CONCEPTS",
    "ModelKnowledgeEntry",
    "SpecializationOverride",
    "get_model_knowledge",
    "get_override",
    "normalize",
    "resolve_specializations",
]
