"""
PARIKA Scored Memory

Immutable value object pairing a Memory with its retrieval score and a
transparency breakdown, mirroring the Model Selection Framework's
RuleOutcome/ModelSelectionResult transparency pattern.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType

from .memory import Memory


@dataclass(frozen=True, slots=True, kw_only=True)
class ScoredMemory:
    """
    A Memory returned from MemoryManager.search(), with its score.

    Attributes
    ----------
    memory:
        The matched memory.

    score:
        Final composite score (higher is more relevant).

    breakdown:
        Per-signal contribution (e.g. "relevance", "recency",
        "importance", "frequency") for transparency/debugging. Purely
        deterministic arithmetic -- never an interpretation of content.
    """

    memory: Memory
    score: float
    breakdown: MappingProxyType[str, float] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        if type(self.memory) is not Memory:
            raise TypeError("memory must be a Memory.")

        if type(self.score) is not float:
            raise TypeError("score must be a float.")

        object.__setattr__(
            self, "breakdown", MappingProxyType(dict(self.breakdown))
        )
