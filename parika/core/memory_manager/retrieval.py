"""
PARIKA Memory Retrieval

Deterministic, lexical-only scoring for MemoryManager.search().

This module performs pure arithmetic over already-stored, structural
values (a SQLite FTS5 `bm25()` rank, timestamps, an existing importance
score, an access count). It never performs semantic search, never
generates an embedding, and never interprets memory content -- see
Core_Component_Responsibilities.md's MemoryManager "Does NOT" list and
docs/architecture/Intelligence_Foundation_Design.md section 4.3.
"""

from __future__ import annotations

import math

from datetime import datetime, UTC
from types import MappingProxyType

from .config import MemoryManagerConfig
from .memory import Memory
from .scored_memory import ScoredMemory


def _relevance_score(bm25_rank: float | None) -> float:
    """
    Convert a SQLite FTS5 bm25() rank into a "higher is better" score.

    SQLite's bm25() returns lower-is-better values (a cost, not a
    similarity). A candidate with no text query (bm25_rank is None) gets
    a neutral relevance contribution of 0.0 rather than being penalized.
    """

    if bm25_rank is None:
        return 0.0

    return 1.0 / (1.0 + max(0.0, bm25_rank))


def _recency_score(
    updated_at: datetime,
    *,
    now: datetime,
    half_life_seconds: float,
) -> float:
    """Exponential recency decay in [0, 1]; 1.0 for "just updated"."""

    if half_life_seconds <= 0:
        return 1.0

    age_seconds = max(0.0, (now - updated_at).total_seconds())

    return 0.5 ** (age_seconds / half_life_seconds)


def _frequency_score(access_count: int) -> float:
    """Diminishing-returns access-frequency signal."""

    return math.log1p(max(0, access_count))


def score_candidate(
    memory: Memory,
    *,
    bm25_rank: float | None,
    config: MemoryManagerConfig,
    now: datetime | None = None,
) -> ScoredMemory:
    """
    Compute a ScoredMemory for one candidate.

    Parameters
    ----------
    memory:
        Candidate memory.

    bm25_rank:
        SQLite FTS5 bm25() rank for this candidate, or None if the
        search had no text query.

    config:
        Weight configuration.

    now:
        Reference time for recency decay; defaults to the current UTC
        time.

    Returns
    -------
    ScoredMemory
        The candidate with its composite score and per-signal breakdown.
    """

    reference_time = now if now is not None else datetime.now(UTC)

    relevance = _relevance_score(bm25_rank) * config.relevance_weight
    recency = (
        _recency_score(
            memory.updated_at,
            now=reference_time,
            half_life_seconds=config.recency_half_life_seconds,
        )
        * config.recency_weight
    )
    importance = memory.importance_score * config.importance_weight
    frequency = _frequency_score(memory.access_count) * config.frequency_weight
    # How confident PARIKA is this memory is accurate and current (see
    # memory.confidence, increased by remember() when a duplicate is
    # merged) -- Phase 1 Completion Specification section 4 explicitly
    # lists confidence as a ranking factor, distinct from importance.
    confidence = memory.confidence * config.confidence_weight

    total = relevance + recency + importance + frequency + confidence

    return ScoredMemory(
        memory=memory,
        score=total,
        breakdown=MappingProxyType(
            {
                "relevance": relevance,
                "recency": recency,
                "importance": importance,
                "frequency": frequency,
                "confidence": confidence,
            }
        ),
    )


def rank_candidates(
    candidates: tuple[tuple[Memory, float | None], ...],
    *,
    config: MemoryManagerConfig,
    limit: int,
    offset: int,
    now: datetime | None = None,
) -> tuple[ScoredMemory, ...]:
    """
    Score every candidate, sort descending by score, and paginate.

    Parameters
    ----------
    candidates:
        Tuples of (Memory, bm25_rank_or_None).

    config:
        Weight configuration.

    limit, offset:
        Pagination window applied after sorting.

    now:
        Reference time for recency decay.

    Returns
    -------
    tuple[ScoredMemory, ...]
        Paginated, score-sorted results.
    """

    scored = [
        score_candidate(memory, bm25_rank=bm25_rank, config=config, now=now)
        for memory, bm25_rank in candidates
    ]

    scored.sort(key=lambda item: item.score, reverse=True)

    return tuple(scored[offset : offset + limit])
