"""
PARIKA Knowledge Source

Defines the authoritative immutable representation of a knowledge source.

A KnowledgeSource represents where knowledge originates. It contains only
metadata describing the source and never stores extracted knowledge,
indexes, search results, or parser state.

Examples
--------
- PARIKA source repository
- Python documentation
- Laravel documentation
- PDF collection
- Local workspace

Notes
-----
KnowledgeSource is the authoritative object within the KnowledgeManager
bounded context. All extracted Knowledge objects are derived from a
KnowledgeSource and may be regenerated at any time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Mapping
from uuid import UUID

from .exceptions import InvalidKnowledgeSourceError
from .source_kind import KnowledgeSourceKind
from .source_status import KnowledgeSourceStatus


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class KnowledgeSource:
    """
    Immutable authoritative description of a knowledge source.

    A KnowledgeSource identifies and describes where knowledge originates.
    It does not contain extracted knowledge or indexing information.
    """

    id: UUID
    """Globally unique identifier."""

    name: str
    """Human-readable source name."""

    kind: KnowledgeSourceKind
    """Logical classification of the knowledge source."""

    location: str
    """Location of the knowledge source."""

    status: KnowledgeSourceStatus
    """Current lifecycle status."""

    description: str | None = None
    """Optional human-readable description."""

    metadata: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    """Immutable engine-specific metadata."""

    created_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )
    """Creation timestamp."""

    content_hash: str | None = None
    """Opaque content hash computed by the resolved engine/driver, used
    for incremental re-indexing (see KnowledgeManager.index_incremental()).
    KnowledgeManager only ever compares this value for equality; it
    never computes or interprets it."""

    last_indexed_at: datetime | None = None
    """Timestamp of the most recent successful index() call, if any."""

    def __post_init__(self) -> None:
        """
        Validate and normalize the knowledge source.
        """

        name = self.name.strip()
        if not name:
            raise InvalidKnowledgeSourceError(
                "Knowledge source name cannot be empty."
            )

        location = self.location.strip()
        if not location:
            raise InvalidKnowledgeSourceError(
                "Knowledge source location cannot be empty."
            )

        object.__setattr__(self, "name", name)
        object.__setattr__(self, "location", location)

        if self.description is not None:
            description = self.description.strip()
            object.__setattr__(
                self,
                "description",
                description if description else None,
            )

        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )

        if self.content_hash is not None and type(self.content_hash) is not str:
            raise InvalidKnowledgeSourceError(
                "content_hash must be a string or None."
            )

        if self.content_hash is not None and not self.content_hash.strip():
            raise InvalidKnowledgeSourceError(
                "content_hash cannot be an empty string."
            )

        if self.last_indexed_at is not None and type(self.last_indexed_at) is not datetime:
            raise InvalidKnowledgeSourceError(
                "last_indexed_at must be a datetime or None."
            )

    def __hash__(self) -> int:
        """
        Hash using only the unique identifier.
        """
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        """
        Equality is based solely on identity.
        """
        if not isinstance(other, KnowledgeSource):
            return NotImplemented

        return self.id == other.id