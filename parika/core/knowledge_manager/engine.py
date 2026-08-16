"""
PARIKA Knowledge Engine

Defines the contract implemented by knowledge engines.

A KnowledgeEngine is responsible for extracting Knowledge from a
KnowledgeSource, indexing it, removing indexed data, and executing
search operations.

KnowledgeManager coordinates engines but does not implement engine
behavior itself.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .knowledge_source import KnowledgeSource
from .search_query import SearchQuery
from .search_result import SearchResult


class KnowledgeEngine(ABC):
    """
    Contract implemented by all knowledge engines.
    """

    @abstractmethod
    def supports(self, source: KnowledgeSource) -> bool:
        """
        Determine whether this engine supports the given knowledge source.
        """
        raise NotImplementedError

    @abstractmethod
    def index(self, source: KnowledgeSource) -> int:
        """
        Build or rebuild the search index for a knowledge source.

        Returns the number of indexed knowledge units.
        """
        raise NotImplementedError

    @abstractmethod
    def remove(self, source: KnowledgeSource) -> None:
        """
        Remove all indexed data for a knowledge source.
        """
        raise NotImplementedError

    @abstractmethod
    def search(self, sources: tuple[KnowledgeSource, ...], query: SearchQuery) -> tuple[SearchResult, ...]:
        """
        Execute a search over the specified knowledge sources.
        """
        raise NotImplementedError