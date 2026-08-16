"""
PARIKA Consolidation Policy

Immutable value object describing a deterministic, read-only selection
of candidate memories for consolidation. MemoryManager only selects
candidates by this policy -- it never summarizes or interprets them; see
docs/architecture/Intelligence_Foundation_Design.md section 4.3.
"""

from __future__ import annotations

from dataclasses import dataclass

from .memory_kind import MemoryKind
from .memory_scope import MemoryScope


@dataclass(frozen=True, slots=True, kw_only=True)
class ConsolidationPolicy:
    """
    Deterministic selection criteria for consolidation candidates.

    Attributes
    ----------
    scope:
        Scope to select candidates from.

    session_id:
        Optional session filter.

    kind:
        Kind to select candidates from (typically SHORT_TERM).

    older_than_seconds:
        Minimum age (by updated_at) in seconds for a candidate.

    max_access_count:
        Candidates must have an access_count at or below this value.
    """

    scope: MemoryScope
    session_id: str | None = None
    kind: MemoryKind = MemoryKind.SHORT_TERM
    older_than_seconds: int = 3600
    max_access_count: int = 1

    def __post_init__(self) -> None:
        if type(self.scope) is not MemoryScope:
            raise TypeError("scope must be a MemoryScope.")

        if type(self.kind) is not MemoryKind:
            raise TypeError("kind must be a MemoryKind.")

        if type(self.older_than_seconds) is not int or self.older_than_seconds < 0:
            raise ValueError("older_than_seconds must be a non-negative int.")

        if type(self.max_access_count) is not int or self.max_access_count < 0:
            raise ValueError("max_access_count must be a non-negative int.")
