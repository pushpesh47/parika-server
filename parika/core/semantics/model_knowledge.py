"""
PARIKA Core - PARIKA Model Knowledge

Owns two deliberately separate kinds of PARIKA-curated, per-model
data, both keyed by a model's exact base name (the portion of a model
id before any `:tag` suffix, e.g. Ollama's `"glm-ocr:latest"` ->
`"glm-ocr"`), case-insensitive, via `_base_name()`:

1. Local Curated Override (`SpecializationOverride`/`get_override()`)
   -- unchanged in role from before this module's evolution: PARIKA's
   hand-curated corrections to a model's *provider-facing*
   `ProviderModel.specializations` set (see `resolution
   .resolve_specializations()`), consumed by the Model Selection
   Framework's filtering/scoring pipeline exactly as before. Still an
   input to an *objective provider fact* (`ProviderModel
   .specializations`), however curated its origin -- Planner,
   `filtering.py`, and `rules.py` are completely unaffected by
   anything below and by this module's evolution.

2. PARIKA Model Knowledge (`ModelKnowledgeEntry`/`get_model_knowledge()`)
   -- PARIKA's own observed knowledge about a model's real-world
   strengths, obtained through benchmarking, manual testing, or
   evaluation (e.g. "this specific vision model is noticeably better
   at reading UI screenshots than at general chart reading, even
   though both are tagged `vision_understanding`"). This is NEVER
   provider metadata, and it NEVER feeds `ProviderModel`, `filtering
   .py`, or `rules.py` -- it exists solely to be surfaced, clearly
   labeled as PARIKA's own knowledge and never blended with provider
   facts, inside the worker model inventory an AI-assisted routing
   model reasons over (see `parika/interfaces/ai_context
   /worker_inventory.py`). Deliberately a plain, hand-maintained data
   table today, exactly like Local Curated Override already was --
   kept behind the one narrow `get_model_knowledge()` lookup function
   precisely so a future benchmark-driven source can replace or
   augment it later without changing any consumer's code.

Both tables are:

    - Keyed by model id, never by provider - each applies uniformly to
      any provider that ever surfaces a model under a matching id
      (e.g. the same open-weight model re-hosted by two different
      providers).
    - Plain, hand-maintained data tables, not learned or
      auto-discovered ones.
    - Provider-independent: nothing here understands Ollama, OpenAI,
      or any other provider's raw metadata format.

Matching is by exact model base name, case-insensitive. Substring/
prefix matching and model-family heuristics are deliberately not
implemented - add a new entry, keyed by its own exact base name,
whenever a new model needs a correction or PARIKA gains new observed
knowledge about it.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SpecializationOverride:
    """
    A single model's curated correction to its Provider Metadata
    specialization evidence.

    Applied as `(provider_reported - remove) | add` (see
    `resolution.resolve_specializations()`). Both sets default to
    empty, so an override may freely choose to only add, only remove,
    or both.
    """

    remove: frozenset[str] = field(default_factory=frozenset)
    """Specialization concepts to strip from the provider-reported set."""

    add: frozenset[str] = field(default_factory=frozenset)
    """Specialization concepts to add, regardless of what the provider reported."""


@dataclass(frozen=True, slots=True)
class ModelKnowledgeEntry:
    """
    PARIKA's own observed knowledge about one model, obtained through
    benchmarking, manual testing, or evaluation -- never provider
    metadata (see this module's own docstring).
    """

    strengths: frozenset[str] = field(default_factory=frozenset)
    """
    Free-form tags describing tasks PARIKA has observed this specific
    model to be particularly good at (e.g. `"ocr"`,
    `"document_understanding"`, `"ui_analysis"`, `"chart_analysis"`,
    `"refactoring"`, `"code_generation"`). Deliberately not the same
    closed vocabulary `task_classification.TaskCategory` uses for hard
    filtering: this is informational, routing-facing knowledge, not a
    filtering dimension, and may be arbitrarily more specific than
    any registered `TaskCategory`.
    """

    notes: str = ""
    """Optional free-text observation, for human/operator context only."""


_MODEL_OVERRIDES: dict[str, SpecializationOverride] = {
    "qwen3-vl": SpecializationOverride(
        remove=frozenset({"general_chat"}),
        add=frozenset({"vision_understanding", "ocr", "document_understanding"}),
    ),
    "minicpm-v4.5": SpecializationOverride(
        remove=frozenset({"general_chat"}),
        add=frozenset({"vision_understanding", "ocr", "document_understanding"}),
    ),
    "medgemma1.5":  SpecializationOverride(
        remove=frozenset({"general_chat"}),
        add=frozenset({"vision_understanding", "ocr", "document_understanding"}),
    ),
}
"""
Hand-curated corrections, keyed by exact, lowercased model base name.

These entries fix the known bug where Ollama's `"completion"`
capability (reported by every text-generating model, including
vision/OCR-specialized ones) causes such a model to be mis-mapped as a
`"general_chat"` model (see `parika/providers/ollama/model_mapping.py`
`_CAPABILITY_SPECIALIZATION_MAP`). `minicpm-v4.5` is a general-purpose
vision-language model (image description, VQA, object detection,
scene/UI/chart/diagram understanding, as well as OCR/document
understanding), so it is tagged with `"vision_understanding"` in
addition to `"ocr"`/`"document_understanding"` -- this is what lets it
satisfy `TaskCategory.VISION_UNDERSTANDING`'s
`required_specializations={"vision_understanding"}` filter (see
`parika.core.planner.model_selection.task_classification`) and
therefore be selected for the Vision Module's Capabilities
(`parika/modules/vision/`), exactly the same mechanism that already
selects it (and `glm-ocr`) for the OCR Module. Add further entries
here, following the same shape, whenever a new model is discovered to
need a correction - no other code needs to change.
"""

_MODEL_KNOWLEDGE: dict[str, ModelKnowledgeEntry] = {
    "qwen3-vl": ModelKnowledgeEntry(
        strengths=frozenset(
            {
                "vision_understanding",
                "ocr",
                "document_understanding",
                "ui_analysis",
                "chart_analysis",
                "video_understanding",
            }
        ),
        notes=(
            "Vision-language model; strong fit for visual reasoning, "
            "OCR, documents, UI screenshots, charts, diagrams, and video understanding."
        ),
    ),
    "minicpm-v4.5": ModelKnowledgeEntry(
        strengths=frozenset(
            {
                "vision_understanding",
                "ocr",
                "document_understanding",
                "ui_analysis",
                "chart_analysis",
                "video_understanding",
            }
        ),
        notes=(
            "General-purpose vision-language model; broad coverage "
            "across OCR, documents, UI, charts, diagrams, and video understanding."
        ),
    ),
}
"""
PARIKA's own observed knowledge, keyed by exact, lowercased model base
name -- see `ModelKnowledgeEntry`'s docstring and this module's own
docstring for why this is deliberately separate from
`_MODEL_OVERRIDES` above. Add further entries here, following the
same shape, whenever PARIKA gains new observed knowledge about a
model (manual evaluation today; a future benchmark-driven source may
populate this table, or a replacement for it, without any consumer
needing to change - see `get_model_knowledge()`).
"""


def _base_name(model_id: str) -> str:
    """
    Strip an Ollama-style `:tag` suffix (if any) and lowercase, so
    `"glm-ocr:latest"`, `"glm-ocr:q4_0"`, and `"GLM-OCR"` all match the
    same entry.
    """

    return model_id.split(":", 1)[0].strip().lower()


def get_override(model_id: str) -> SpecializationOverride | None:
    """
    Return the curated `SpecializationOverride` for a model id, or
    `None` when no override is registered for it.
    """

    return _MODEL_OVERRIDES.get(_base_name(model_id))


def get_model_knowledge(model_id: str) -> ModelKnowledgeEntry | None:
    """
    Return PARIKA's own observed `ModelKnowledgeEntry` for a model id,
    or `None` when PARIKA has no observed knowledge about it yet.

    This is the one seam consumers (currently only
    `parika/interfaces/ai_context/worker_inventory.py`) depend on --
    kept deliberately narrow so a future benchmark-driven knowledge
    source can replace or augment `_MODEL_KNOWLEDGE` above without
    requiring any change here or in any caller.
    """

    return _MODEL_KNOWLEDGE.get(_base_name(model_id))
