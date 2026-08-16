"""
PARIKA Search Result

Defines the immutable representation of a search result.

A SearchResult represents a successful match returned by a knowledge
search operation. It references the matched Knowledge object together
with the relevance score assigned by the search backend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from .exceptions import InvalidSearchResultError
from .knowledge import Knowledge


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchResult:
    """
    Immutable search result.

    Represents a matched Knowledge object and its associated search
    metadata.
    """

    knowledge: Knowledge
    """Matched knowledge."""

    score: float
    """Relevance score."""

    metadata: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    """Immutable backend-specific metadata."""

    def __post_init__(self) -> None:
        """
        Validate and normalize the search result.
        """

        if self.score < 0:
            raise InvalidSearchResultError(
                "Search result score cannot be negative."
            )

        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )