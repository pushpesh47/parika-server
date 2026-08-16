"""
PARIKA Prune Policy

Immutable value object describing a deterministic memory pruning
request. Pruning is mechanical (TTL expiry, per-scope capacity) and
never inspects memory content.
"""

from __future__ import annotations

from dataclasses import dataclass

from .memory_scope import MemoryScope


@dataclass(frozen=True, slots=True, kw_only=True)
class PrunePolicy:
    """
    Deterministic pruning criteria.

    Attributes
    ----------
    scope:
        Optional scope filter. None applies to every scope.

    session_id:
        Optional session filter.

    respect_decay:
        When True (default), prune memories whose decay_at has passed.

    max_per_scope:
        When set, prune the least valuable (lowest importance_score,
        then oldest last_accessed_at) memories exceeding this count
        within the selected scope/session.
    """

    scope: MemoryScope | None = None
    session_id: str | None = None
    respect_decay: bool = True
    max_per_scope: int | None = None

    def __post_init__(self) -> None:
        if self.scope is not None and type(self.scope) is not MemoryScope:
            raise TypeError("scope must be a MemoryScope or None.")

        if self.session_id is not None and type(self.session_id) is not str:
            raise TypeError("session_id must be a string or None.")

        if type(self.respect_decay) is not bool:
            raise TypeError("respect_decay must be a bool.")

        if self.max_per_scope is not None and (
            type(self.max_per_scope) is not int or self.max_per_scope < 0
        ):
            raise ValueError("max_per_scope must be a non-negative int or None.")
