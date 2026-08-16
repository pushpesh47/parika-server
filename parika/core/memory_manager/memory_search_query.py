"""
PARIKA Memory Search Query

Immutable value object describing a MemoryManager.search() request.
"""

from __future__ import annotations

from dataclasses import dataclass

from .memory_category import MemoryCategory
from .memory_kind import MemoryKind
from .memory_scope import MemoryScope


@dataclass(frozen=True, slots=True, kw_only=True)
class MemorySearchQuery:
    """
    Describes a memory search request.

    Attributes
    ----------
    text:
        Free-text query matched lexically (SQLite FTS5 `bm25()`) against
        memory content. An empty string matches on filters only.

    scope:
        Optional scope filter.

    session_id:
        Optional session filter.

    kind:
        Optional kind filter.

    category:
        Optional content-domain category filter.

    limit:
        Maximum number of results to return.

    offset:
        Number of highest-ranked results to skip.
    """

    text: str = ""
    scope: MemoryScope | None = None
    session_id: str | None = None
    kind: MemoryKind | None = None
    category: MemoryCategory | None = None
    limit: int = 20
    offset: int = 0

    def __post_init__(self) -> None:
        if type(self.text) is not str:
            raise TypeError("text must be a string.")

        if self.scope is not None and type(self.scope) is not MemoryScope:
            raise TypeError("scope must be a MemoryScope or None.")

        if self.session_id is not None and type(self.session_id) is not str:
            raise TypeError("session_id must be a string or None.")

        if self.kind is not None and type(self.kind) is not MemoryKind:
            raise TypeError("kind must be a MemoryKind or None.")

        if self.category is not None and type(self.category) is not MemoryCategory:
            raise TypeError("category must be a MemoryCategory or None.")

        if type(self.limit) is not int or self.limit <= 0:
            raise ValueError("limit must be a positive int.")

        if type(self.offset) is not int or self.offset < 0:
            raise ValueError("offset must be a non-negative int.")
