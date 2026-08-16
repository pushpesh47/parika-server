"""
PARIKA Knowledge Storage

Defines the storage contract for KnowledgeSource persistence.

KnowledgeStorage is responsible only for persisting and retrieving
KnowledgeSource objects. It does not manage indexing, searching,
knowledge extraction, or business logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from uuid import UUID

from .knowledge_source import KnowledgeSource


class KnowledgeStorage(ABC):
    """
    Storage contract for KnowledgeSource persistence.
    """

    @abstractmethod
    def save(self, source: KnowledgeSource) -> None:
        """
        Persist a knowledge source.
        """
        raise NotImplementedError

    @abstractmethod
    def update(self, source: KnowledgeSource) -> None:
        """
        Update an existing knowledge source.
        """
        raise NotImplementedError

    @abstractmethod
    def delete(self, source_id: UUID) -> None:
        """
        Remove a knowledge source.
        """
        raise NotImplementedError

    @abstractmethod
    def get(self, source_id: UUID) -> KnowledgeSource:
        """
        Retrieve a knowledge source by its identifier.
        """
        raise NotImplementedError

    @abstractmethod
    def contains(self, source_id: UUID) -> bool:
        """
        Determine whether a knowledge source exists.
        """
        raise NotImplementedError

    @abstractmethod
    def get_all(self) -> tuple[KnowledgeSource, ...]:
        """
        Retrieve all knowledge sources.
        """
        raise NotImplementedError

    @abstractmethod
    def count(self) -> int:
        """
        Return the number of stored knowledge sources.
        """
        raise NotImplementedError

    @abstractmethod
    def get_many(self, source_ids: frozenset[UUID]) -> tuple[KnowledgeSource, ...]:
        """
        Retrieve multiple knowledge sources by their identifiers.
        """
        raise NotImplementedError