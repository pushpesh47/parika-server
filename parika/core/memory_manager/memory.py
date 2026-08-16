"""
PARIKA Memory

Defines the immutable Memory domain model managed by the MemoryManager.

A Memory represents a single persistent unit of information retained by
PARIKA. It is an immutable value object containing only validated data and
carries no persistence, retrieval, lifecycle, reasoning, or business logic.
"""

from __future__ import annotations

import math

from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any

from .memory_category import MemoryCategory
from .memory_importance import MemoryImportance
from .memory_kind import MemoryKind
from .memory_origin import MemoryOrigin
from .memory_scope import MemoryScope


@dataclass(frozen=True, slots=True, kw_only=True)
class Memory:
    """
    Immutable persistent memory.

    A Memory represents a single validated unit of information retained by
    the MemoryManager.

    Attributes:
        memory_id:
            Globally unique memory identifier.

        kind:
            Classification of the memory.

        origin:
            Origin of the memory.

        content:
            Memory content.

        created_at:
            UTC timestamp when the memory was created.

        updated_at:
            UTC timestamp when the memory was last updated.

        tags:
            Immutable set of memory tags.

        metadata:
            Immutable memory metadata.

        scope:
            Scope at which the memory applies (session/user/workspace/
            global). Defaults to SESSION.

        session_id:
            Identifier of the session this memory was created in, if any.

        importance_score:
            Deterministic, caller-or-rule-supplied importance signal used
            by retrieval ranking. Defaults to 0.0 (neutral).

        access_count:
            Number of times this memory has been retrieved via
            MemoryManager.touch(). Defaults to 0.

        last_accessed_at:
            UTC timestamp of the most recent access, if any.

        decay_at:
            Optional UTC timestamp after which this memory is eligible for
            pruning. None means the memory never expires.

        category:
            Content-domain classification (profile/preference/relationship/
            goal/project/skill/fact/reminder_reference/custom). Every
            permanent memory belongs to exactly one category. Orthogonal to
            `kind` -- see `memory_category.py`.

        importance:
            Human-facing importance level (critical/high/normal/low),
            used by CLI display and by `MemoryManager.remember()`'s
            convenience API to derive a default `importance_score` when
            the caller does not supply one explicitly. See
            `memory_importance.py`.

        confidence:
            How confident PARIKA is that this memory is accurate and
            current, in [0.0, 1.0]. Increased automatically when a
            duplicate is detected and merged into this memory (see
            `MemoryManager.remember()`); defaults to 1.0 for an
            explicitly caller-asserted memory.
    """

    memory_id: str
    kind: MemoryKind
    origin: MemoryOrigin
    content: str
    created_at: datetime
    updated_at: datetime

    tags: frozenset[str] = field(
        default_factory=frozenset
    )

    metadata: MappingProxyType[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    scope: MemoryScope = MemoryScope.SESSION
    session_id: str | None = None
    importance_score: float = 0.0
    access_count: int = 0
    last_accessed_at: datetime | None = None
    decay_at: datetime | None = None
    category: MemoryCategory = MemoryCategory.CUSTOM
    importance: MemoryImportance = MemoryImportance.NORMAL
    confidence: float = 1.0

    def __post_init__(self) -> None:
        """
        Validate the Memory after initialization.
        """

        if type(self.memory_id) is not str:
            raise TypeError("memory_id must be a string.")

        if not self.memory_id.strip():
            raise ValueError("memory_id cannot be empty.")

        if type(self.kind) is not MemoryKind:
            raise TypeError("kind must be a MemoryKind.")

        if type(self.origin) is not MemoryOrigin:
            raise TypeError("origin must be a MemoryOrigin.")

        if type(self.content) is not str:
            raise TypeError("content must be a string.")

        if not self.content.strip():
            raise ValueError("content cannot be empty.")

        if type(self.created_at) is not datetime:
            raise TypeError("created_at must be a datetime.")

        if type(self.updated_at) is not datetime:
            raise TypeError("updated_at must be a datetime.")

        if self.updated_at < self.created_at:
            raise ValueError(
                "updated_at cannot be earlier than created_at."
            )

        if type(self.tags) is not frozenset:
            raise TypeError("tags must be a frozenset.")

        for tag in self.tags:
            if type(tag) is not str:
                raise TypeError("all tags must be strings.")

            if not tag.strip():
                raise ValueError("tags cannot contain empty strings.")

        if type(self.metadata) is not MappingProxyType:
            raise TypeError("metadata must be a MappingProxyType.")

        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )

        if type(self.scope) is not MemoryScope:
            raise TypeError("scope must be a MemoryScope.")

        if self.session_id is not None and type(self.session_id) is not str:
            raise TypeError("session_id must be a string or None.")

        if self.session_id is not None and not self.session_id.strip():
            raise ValueError("session_id cannot be an empty string.")

        if type(self.importance_score) is not float:
            raise TypeError("importance_score must be a float.")

        if not math.isfinite(self.importance_score):
            raise ValueError("importance_score must be finite.")

        if type(self.access_count) is not int:
            raise TypeError("access_count must be an int.")

        if self.access_count < 0:
            raise ValueError("access_count cannot be negative.")

        if self.last_accessed_at is not None and type(self.last_accessed_at) is not datetime:
            raise TypeError("last_accessed_at must be a datetime or None.")

        if self.decay_at is not None and type(self.decay_at) is not datetime:
            raise TypeError("decay_at must be a datetime or None.")

        if type(self.category) is not MemoryCategory:
            raise TypeError("category must be a MemoryCategory.")

        if type(self.importance) is not MemoryImportance:
            raise TypeError("importance must be a MemoryImportance.")

        if type(self.confidence) is not float:
            raise TypeError("confidence must be a float.")

        if not math.isfinite(self.confidence) or not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be a finite float in [0.0, 1.0].")