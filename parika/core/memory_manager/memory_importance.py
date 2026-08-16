"""
PARIKA Memory Importance

Defines the supported human-facing importance levels for persistent
memories, and their deterministic mapping onto the continuous
`Memory.importance_score` retrieval-ranking signal.

`MemoryImportance` is categorical (for display/API ergonomics, e.g.
the `/memory` CLI command and `remember()`'s convenience API);
`Memory.importance_score` remains the continuous value
`retrieval.py`'s scoring blend actually consumes. `default_score_for()`
is the single, pure mapping between the two -- callers may still
supply an explicit `importance_score` that overrides this default.
"""

from __future__ import annotations

from enum import StrEnum

_DEFAULT_SCORES: dict[str, float] = {
    "critical": 1.0,
    "high": 0.75,
    "normal": 0.5,
    "low": 0.25,
}


class MemoryImportance(StrEnum):
    """Human-facing importance level of a persistent memory."""

    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


def default_score_for(importance: MemoryImportance) -> float:
    """Return the deterministic default `importance_score` for a level."""

    return _DEFAULT_SCORES[importance.value]
