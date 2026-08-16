"""
PARIKA Knowledge

Defines the immutable normalized representation of extracted knowledge.

Knowledge is derived from a KnowledgeSource and represents a single
searchable unit of information.

Examples
--------
- Class
- Function
- Method
- API endpoint
- Documentation section
- Markdown heading
- Paragraph
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Mapping
from uuid import UUID

from .exceptions import InvalidKnowledgeError


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class Knowledge:
    """
    Immutable normalized knowledge unit.

    A Knowledge object is derived from a KnowledgeSource and represents
    a single searchable piece of information.
    """

    id: UUID
    """Globally unique identifier."""

    source_id: UUID
    """KnowledgeSource from which this knowledge was extracted."""

    title: str
    """Human-readable title."""

    content: str
    """Normalized searchable content."""

    location: str
    """Logical location within the source."""

    metadata: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    """Immutable engine-specific metadata."""

    created_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )
    """Creation timestamp."""

    def __post_init__(self) -> None:
        """
        Validate and normalize the knowledge object.
        """

        title = self.title.strip()
        if not title:
            raise InvalidKnowledgeError(
                "Knowledge title cannot be empty."
            )

        content = self.content.strip()
        if not content:
            raise InvalidKnowledgeError(
                "Knowledge content cannot be empty."
            )

        location = self.location.strip()
        if not location:
            raise InvalidKnowledgeError(
                "Knowledge location cannot be empty."
            )

        object.__setattr__(self, "title", title)
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "location", location)

        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
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
        if not isinstance(other, Knowledge):
            return NotImplemented

        return self.id == other.id