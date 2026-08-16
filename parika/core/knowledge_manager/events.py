"""
PARIKA Knowledge Manager Events

Defines immutable event payloads published by KnowledgeManager.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class KnowledgeSourceRegisteredEvent:
    """
    Published when a knowledge source is registered.
    """

    source_id: UUID

    occurred_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class KnowledgeSourceUpdatedEvent:
    """
    Published when a knowledge source is updated.
    """

    source_id: UUID

    occurred_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class KnowledgeSourceRemovedEvent:
    """
    Published when a knowledge source is removed.
    """

    source_id: UUID

    occurred_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class KnowledgeIndexedEvent:
    """
    Published when a knowledge source has been indexed.
    """

    source_id: UUID

    knowledge_count: int

    occurred_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class KnowledgeIndexRemovedEvent:
    """
    Published when an indexed knowledge source has been removed.
    """

    source_id: UUID

    occurred_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )