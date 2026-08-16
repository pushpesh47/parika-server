"""
PARIKA Search Query

Immutable search request used by KnowledgeManager.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping
from uuid import UUID

from .exceptions import InvalidSearchQueryError


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchQuery:
    """
    Immutable search request.

    Describes what should be searched without defining how the search
    is executed.
    """

    text: str

    source_ids: frozenset[UUID] = frozenset()

    limit: int = 20

    offset: int = 0

    include_disabled: bool = False

    metadata_filters: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:

        text = self.text.strip()

        if not text:
            raise InvalidSearchQueryError(
                "Search text cannot be empty."
            )

        if self.limit <= 0:
            raise InvalidSearchQueryError(
                "Limit must be greater than zero."
            )

        if self.offset < 0:
            raise InvalidSearchQueryError(
                "Offset cannot be negative."
            )

        object.__setattr__(self, "text", text)

        object.__setattr__(
            self,
            "metadata_filters",
            MappingProxyType(dict(self.metadata_filters)),
        )

        object.__setattr__(
            self,
            "source_ids",
            frozenset(self.source_ids),
        )