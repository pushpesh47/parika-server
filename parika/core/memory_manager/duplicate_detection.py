"""
PARIKA Memory Duplicate Detection

Deterministic, stdlib-only similarity scoring used by
`MemoryManager.remember()` to detect when new content is a duplicate
of an already-stored memory, so PARIKA never creates unnecessary
duplicate memories (e.g. "User is Pushpesh" / "User's name is
Pushpesh" / "Name = Pushpesh" all describe the same fact).

This uses `difflib.SequenceMatcher` -- the same stdlib-only,
zero-dependency approach already used for title-similarity
deduplication in `parika/tools/web_search/dedup.py` -- as a
deterministic proxy for "semantic similarity" between two short pieces
of free-form text. This is lexical, not embedding-based: it never
performs true semantic/vector search, honoring MemoryManager's
documented "Does NOT perform semantic search / generate embeddings"
boundary (see Core_Component_Responsibilities.md) while still
satisfying the practical need to recognize near-duplicate phrasing of
the same fact.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from .memory import Memory

DEFAULT_DUPLICATE_SIMILARITY_THRESHOLD: float = 0.82


def content_similarity(a: str, b: str) -> float:
    """Return a deterministic [0.0, 1.0] similarity ratio between two strings."""

    return SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()


def find_duplicate(
    candidates: tuple[Memory, ...],
    new_content: str,
    *,
    threshold: float = DEFAULT_DUPLICATE_SIMILARITY_THRESHOLD,
) -> Memory | None:
    """
    Return the most similar candidate whose similarity to `new_content`
    meets or exceeds `threshold`, or None if no candidate qualifies.

    When multiple candidates qualify, the single most similar one is
    returned, so at most one canonical memory is ever merged into.
    """

    best_match: Memory | None = None
    best_score = 0.0

    for candidate in candidates:
        score = content_similarity(candidate.content, new_content)

        if score >= threshold and score > best_score:
            best_match = candidate
            best_score = score

    return best_match
