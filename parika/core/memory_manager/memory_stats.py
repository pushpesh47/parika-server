"""
PARIKA Memory Stats

Immutable snapshot returned by `MemoryManager.stats()`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryStats:
    """Aggregate, point-in-time statistics over every stored memory."""

    total: int
    by_category: MappingProxyType[str, int] = field(
        default_factory=lambda: MappingProxyType({})
    )
    by_importance: MappingProxyType[str, int] = field(
        default_factory=lambda: MappingProxyType({})
    )
    by_scope: MappingProxyType[str, int] = field(
        default_factory=lambda: MappingProxyType({})
    )
    storage_size_bytes: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "by_category", MappingProxyType(dict(self.by_category))
        )
        object.__setattr__(
            self, "by_importance", MappingProxyType(dict(self.by_importance))
        )
        object.__setattr__(self, "by_scope", MappingProxyType(dict(self.by_scope)))
