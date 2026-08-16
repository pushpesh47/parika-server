"""
PARIKA Core - Semantic Vocabulary

Owns the canonical Model Selection Framework semantic concept ids,
their known aliases, and normalization.

Responsibility, deliberately narrow (see `parika/core/semantics
/__init__.py`'s module docstring for where this sits in the overall
Semantic Enrichment pipeline):

    - `CANONICAL_CONCEPTS`: the well-known semantic concept ids this
      layer recognizes.
    - `_ALIASES`: alternate spellings/synonyms that normalize to one
      of the canonical ids above.
    - `normalize()`: the one function every evidence source's output
      is passed through before it reaches `ProviderModel
      .specializations`.

This module intentionally does NOT implement:
    - Taxonomy traversal or hierarchical relationships between
      concepts (e.g. "ocr is-a vision_understanding").
    - Confidence scoring.
    - Automatic discovery of new concepts from data.

Unrecognized values are not rejected: `normalize()` passes an unknown
string through unchanged, since `ProviderModel.specializations` is
deliberately open (see that module's docstring) and a provider may
always legitimately advertise a specialization this vocabulary has no
opinion about yet. This module only ever *cleans up* known aliases; it
never validates or gatekeeps.

Canonical concept ids deliberately reuse the same string values as
`parika.core.planner.model_selection.task_classification.TaskCategory`
wherever the two overlap (e.g. `"general_chat"`, `"coding"`, `"ocr"`)
- that overlap is what lets a model's `specializations` be matched, via
plain set intersection, against a task's `required_specializations`
with zero translation step anywhere. This module is still deliberately
independent of `TaskCategory` (no import either direction, in either
file): it is a broader vocabulary of *model* semantic concepts, not
*task* categories, and the two are allowed to diverge - e.g.
`"document_understanding"` below is not itself a `TaskCategory` today,
but a model may already be described by it, ready to be matched by a
future document-understanding task profile without any change here.
"""

from __future__ import annotations

CANONICAL_CONCEPTS: frozenset[str] = frozenset(
    {
        "general_chat",
        "coding",
        "reasoning",
        "planning",
        "tool_use",
        "ocr",
        "document_understanding",
        "vision_understanding",
        "image_generation",
        "image_editing",
        "video_understanding",
        "video_generation",
        "speech_to_text",
        "text_to_speech",
        "translation",
        "embedding",
        "reranking",
        "multimodal",
        "structured_output",
    }
)
"""
The well-known Model Selection Framework semantic concept ids.
Deliberately not closed/enforced (see module docstring): a provider or
a Local Curated Override may still introduce a concept id absent from
this set, and `normalize()` will pass it through unchanged rather than
rejecting it. Extend this set as new well-known concepts emerge; doing
so never requires any change to `normalize()`, `model_knowledge.py`,
or `resolution.py`.
"""

_ALIASES: dict[str, str] = {
    "chat": "general_chat",
    "conversation": "general_chat",
    "code": "coding",
    "programming": "coding",
    "vision": "vision_understanding",
    "vqa": "vision_understanding",
    "image_understanding": "vision_understanding",
    "doc_understanding": "document_understanding",
    "document_ocr": "ocr",
    "asr": "speech_to_text",
    "tts": "text_to_speech",
    "tool_calling": "tool_use",
    "function_calling": "tool_use",
}
"""
Known alternate spellings/synonyms that normalize to one of
`CANONICAL_CONCEPTS`. Purely a lookup table - adding a new alias never
requires any change anywhere else in the Semantic Enrichment pipeline.
"""


def normalize(concept: str) -> str:
    """
    Normalize a raw semantic concept string to its canonical form.

    Returns the value unchanged when it is already one of
    `CANONICAL_CONCEPTS`, or when it has no known alias - normalization
    is best-effort cleanup, never validation (see module docstring).
    """

    if concept in CANONICAL_CONCEPTS:
        return concept

    return _ALIASES.get(concept, concept)
