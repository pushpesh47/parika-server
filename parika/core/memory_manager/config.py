"""
PARIKA Memory Manager Configuration

Typed, read-only configuration for MemoryManager's retrieval scoring,
loaded through the existing Configuration component -- the same
`load_xxx_config(configuration)` pattern already used by
`planner/model_selection/config.py` and `tools/web_search/config.py`.

This is not a parallel configuration system: there is no second file and
no state independent of Configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from parika.core.configuration.configuration import Configuration

_DEFAULT_RELEVANCE_WEIGHT: float = 1.0
_DEFAULT_RECENCY_WEIGHT: float = 0.5
_DEFAULT_IMPORTANCE_WEIGHT: float = 0.5
_DEFAULT_FREQUENCY_WEIGHT: float = 0.25
_DEFAULT_CONFIDENCE_WEIGHT: float = 0.5
_DEFAULT_RECENCY_HALF_LIFE_SECONDS: float = 86400.0  # 1 day
_DEFAULT_CANDIDATE_POOL_MULTIPLIER: int = 5


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryManagerConfig:
    """
    Typed snapshot of MemoryManager's retrieval scoring configuration.

    Every weight blends into MemoryManager.search()'s composite score.
    All signals are deterministic (lexical BM25 rank, recency decay,
    caller-supplied importance, access frequency) -- never semantic or
    embedding-based.
    """

    relevance_weight: float = _DEFAULT_RELEVANCE_WEIGHT
    recency_weight: float = _DEFAULT_RECENCY_WEIGHT
    importance_weight: float = _DEFAULT_IMPORTANCE_WEIGHT
    frequency_weight: float = _DEFAULT_FREQUENCY_WEIGHT
    confidence_weight: float = _DEFAULT_CONFIDENCE_WEIGHT
    recency_half_life_seconds: float = _DEFAULT_RECENCY_HALF_LIFE_SECONDS
    candidate_pool_multiplier: int = _DEFAULT_CANDIDATE_POOL_MULTIPLIER


def load_memory_manager_config(
    configuration: "Configuration | None",
) -> MemoryManagerConfig:
    """
    Load MemoryManagerConfig from the `[memory]` configuration section.

    Parameters
    ----------
    configuration:
        Configuration instance, or None to use built-in defaults.

    Returns
    -------
    MemoryManagerConfig
        Typed, read-only configuration snapshot.
    """

    if configuration is None:
        return MemoryManagerConfig()

    return MemoryManagerConfig(
        relevance_weight=float(
            configuration.get("memory.relevance_weight", _DEFAULT_RELEVANCE_WEIGHT)
        ),
        recency_weight=float(
            configuration.get("memory.recency_weight", _DEFAULT_RECENCY_WEIGHT)
        ),
        importance_weight=float(
            configuration.get("memory.importance_weight", _DEFAULT_IMPORTANCE_WEIGHT)
        ),
        frequency_weight=float(
            configuration.get("memory.frequency_weight", _DEFAULT_FREQUENCY_WEIGHT)
        ),
        confidence_weight=float(
            configuration.get("memory.confidence_weight", _DEFAULT_CONFIDENCE_WEIGHT)
        ),
        recency_half_life_seconds=float(
            configuration.get(
                "memory.recency_half_life_seconds",
                _DEFAULT_RECENCY_HALF_LIFE_SECONDS,
            )
        ),
        candidate_pool_multiplier=int(
            configuration.get(
                "memory.candidate_pool_multiplier",
                _DEFAULT_CANDIDATE_POOL_MULTIPLIER,
            )
        ),
    )
