"""
PARIKA Knowledge Engine Registry

Maintains the registry of KnowledgeEngine implementations.

KnowledgeEngineRegistry is responsible for registering, unregistering,
and resolving knowledge engines. It does not perform knowledge
extraction, indexing, or searching.
"""

from __future__ import annotations

from .engine import KnowledgeEngine
from .exceptions import (
    KnowledgeEngineAlreadyExistsError,
    KnowledgeEngineNotFoundError,
)
from .knowledge_source import KnowledgeSource


class KnowledgeEngineRegistry:
    """
    Registry of knowledge engine implementations.
    """

    def __init__(self) -> None:
        """
        Initialize an empty knowledge engine registry.
        """
        self._engines: list[KnowledgeEngine] = []

    def register(self, engine: KnowledgeEngine) -> None:
        """
        Register a knowledge engine.
        """
        if engine in self._engines:
            raise KnowledgeEngineAlreadyExistsError(
                "Knowledge engine is already registered."
            )

        self._engines.append(engine)

    def unregister(self, engine: KnowledgeEngine) -> None:
        """
        Unregister a knowledge engine.
        """
        try:
            self._engines.remove(engine)
        except ValueError as exc:
            raise KnowledgeEngineNotFoundError(
                "Knowledge engine is not registered."
            ) from exc

    def resolve(self, source: KnowledgeSource) -> KnowledgeEngine:
        """
        Resolve the appropriate engine for a knowledge source.
        """
        for engine in self._engines:
            if engine.supports(source):
                return engine

        raise KnowledgeEngineNotFoundError(
            f"No knowledge engine found for source '{source.name}'."
        )

    def contains(self, engine: KnowledgeEngine) -> bool:
        """
        Determine whether a knowledge engine is registered.
        """
        return engine in self._engines

    def get_all(self) -> tuple[KnowledgeEngine, ...]:
        """
        Return all registered knowledge engines.
        """
        return tuple(self._engines)

    def count(self) -> int:
        """
        Return the number of registered knowledge engines.
        """
        return len(self._engines)

    def clear(self) -> None:
        """
        Remove all registered knowledge engines.
        """
        self._engines.clear()