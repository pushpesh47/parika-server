"""
PARIKA Core - Capability Catalog.

Provider-independent, read-only retrieval/index layer sitting at the
Prompt Engineering stage, between Automatic Capability Discovery
(`CapabilityRegistry.find()`) and native tool-schema construction
(`parika/interfaces/ai_context/tool_context.py`). See
`capability_catalog.py`'s module docstring for the full pipeline and
`docs/architecture/Request_Understanding.md` for the design rationale.

Public API:

- `CapabilityCatalog`: the retrieval orchestrator.
- `CapabilityFamily` / `family_id_for`: the retrieval-family model.
- `LexicalScorer` / `TokenOverlapScorer`: the default lexical
  retrieval strategy, and the extension point for alternatives.
- `SemanticScorer`: the reserved, currently-unimplemented semantic
  retrieval extension point.
- `PipelineStage` / `RetrievalContext`: the extension point for adding
  a future retrieval stage (see `retrieval_context.py` and
  `stages.py`) without changing `CapabilityCatalog`'s public API.
- `RelevanceCutoffResult`: the outcome of Dynamic Relevance Cutoff
  (see `relevance_cutoff.py`) -- what actually determines *how many*
  capabilities are advertised each turn, never a fixed count.

This package never executes anything, never chooses a provider or
model, never invokes a tool, and never replaces `CapabilityRegistry`
or `CapabilityResolver`.
"""

from __future__ import annotations

from .capability_catalog import DEFAULT_BUDGET, CapabilityCatalog
from .capability_family import CapabilityFamily, family_id_for
from .lexical_retrieval import LexicalScorer, TokenOverlapScorer
from .relevance_cutoff import RelevanceCutoffResult
from .retrieval_context import PipelineStage, RetrievalContext
from .semantic_retrieval import SemanticScorer

__all__ = [
    "DEFAULT_BUDGET",
    "CapabilityCatalog",
    "CapabilityFamily",
    "family_id_for",
    "LexicalScorer",
    "TokenOverlapScorer",
    "SemanticScorer",
    "PipelineStage",
    "RetrievalContext",
    "RelevanceCutoffResult",
]
