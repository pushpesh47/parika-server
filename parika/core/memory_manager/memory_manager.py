"""
PARIKA Memory Manager

This module provides the public memory management service for the
PARIKA platform.

Responsibilities
----------------
- Manage the lifecycle of Memory objects.
- Coordinate memory persistence through MemoryStorage.
- Validate public API inputs.
- Ensure thread-safe memory operations.
- Publish memory lifecycle events.

This module intentionally contains no persistence logic.
Persistence is delegated to MemoryStorage.

Thread Safety
-------------
MemoryManager is thread-safe. All public operations are protected
using an internal re-entrant lock.
"""

from __future__ import annotations

from datetime import datetime, UTC
from pathlib import Path, PurePath
from threading import RLock
from typing import TYPE_CHECKING

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.memory_manager.bulk_operations import (
    clear as _bulk_clear,
    list_memories as _bulk_list_memories,
    stats as _bulk_stats,
)
from parika.core.memory_manager.lifecycle import (
    consolidation_candidates as _lifecycle_consolidation_candidates,
    prune as _lifecycle_prune,
    search as _lifecycle_search,
)
from parika.core.memory_manager.config import (
    MemoryManagerConfig,
    load_memory_manager_config,
)
from parika.core.memory_manager.consolidation_policy import ConsolidationPolicy
from parika.core.memory_manager.duplicate_detection import (
    DEFAULT_DUPLICATE_SIMILARITY_THRESHOLD,
)
from parika.core.memory_manager.events import (
    MemoryRegisteredEvent,
    MemoryRemovedEvent,
    MemoryUpdatedEvent,
)
from parika.core.memory_manager.exceptions import (
    InvalidMemoryError,
    MemoryAlreadyExistsError,
    MemoryNotFoundError,
)
from parika.core.memory_manager.memory import Memory
from parika.core.memory_manager.memory_category import MemoryCategory
from parika.core.memory_manager.memory_importance import MemoryImportance
from parika.core.memory_manager.memory_io import (
    export_memories as _io_export_memories,
    import_memories as _io_import_memories,
)
from parika.core.memory_manager.memory_kind import MemoryKind
from parika.core.memory_manager.memory_origin import MemoryOrigin
from parika.core.memory_manager.memory_scope import MemoryScope
from parika.core.memory_manager.memory_search_query import MemorySearchQuery
from parika.core.memory_manager.memory_stats import MemoryStats
from parika.core.memory_manager.prune_policy import PrunePolicy
from parika.core.memory_manager.remember import (
    merge as _remember_merge,
    remember as _remember_remember,
)
from parika.core.memory_manager.scored_memory import ScoredMemory
from parika.core.memory_manager.postgresql_storage import PostgreSQLMemoryStorage
from parika.core.utilities.progress import ProgressReporter

if TYPE_CHECKING:
    from parika.core.configuration.configuration import Configuration


class MemoryManager:
    """
    Thread-safe manager responsible for coordinating Memory objects.

    MemoryManager validates requests, delegates persistence to
    MemoryStorage, and publishes lifecycle events through EventBus.
    """

    __slots__ = (
        "_logger",
        "_event_bus",
        "_storage",
        "_lock",
        "_config",
    )

    def __init__(
        self,
        logger: Logger,
        event_bus: EventBus,
        storage: PostgreSQLMemoryStorage,
        configuration: "Configuration | None" = None,
    ) -> None:
        """
        Initialize a new MemoryManager.

        Parameters
        ----------
        logger:
            Logger instance.

        event_bus:
            EventBus used to publish memory events.

        storage:
            PostgreSQL storage implementation.

        configuration:
            Optional Configuration used to load retrieval scoring
            weights from the `[memory]` section. Existing call sites
            that do not pass this argument are unaffected -- built-in
            defaults are used.
        """

        if type(logger) is not Logger:
            raise TypeError(
                "logger must be of type Logger."
            )

        if type(event_bus) is not EventBus:
            raise TypeError(
                "event_bus must be of type EventBus."
            )

        if storage is None:
            raise TypeError("storage must be provided (PostgreSQLMemoryStorage)")

        self._logger = logger.get_logger(__name__)
        self._event_bus: EventBus = event_bus
        self._storage = storage
        self._lock: RLock = RLock()
        self._config: MemoryManagerConfig = load_memory_manager_config(configuration)

    def initialize(self) -> None:
        """
        Initialize the MemoryManager.

        This method initializes the underlying memory storage.

        Raises
        ------
        MemoryPersistenceError
            If storage initialization fails.
        """

        with self._lock:
            self._logger.info(
                "Initializing MemoryManager."
            )

            self._storage.initialize()

            self._logger.info(
                "MemoryManager initialized successfully."
            )

    def shutdown(self) -> None:
        """
        Shutdown the MemoryManager.

        This method shuts down the underlying memory storage.

        Raises
        ------
        MemoryPersistenceError
            If storage shutdown fails.
        """

        with self._lock:
            self._logger.info(
                "Shutting down MemoryManager."
            )

            self._storage.shutdown()

            self._logger.info(
                "MemoryManager shutdown completed."
            )

    def _validate_memory(
        self,
        memory: Memory,
    ) -> None:
        """
        Validate a Memory object.

        Parameters
        ----------
        memory:
            Memory to validate.

        Raises
        ------
        InvalidMemoryError
            If the memory is invalid.
        """

        if type(memory) is not Memory:
            raise InvalidMemoryError(
                "memory must be of type Memory."
            )

    def _validate_memory_id(
        self,
        memory_id: str,
    ) -> None:
        """
        Validate a memory identifier.

        Parameters
        ----------
        memory_id:
            Memory identifier.

        Raises
        ------
        TypeError
            If memory_id is not a string.

        ValueError
            If memory_id is empty.
        """

        if type(memory_id) is not str:
            raise TypeError(
                "memory_id must be of type str."
            )

        if not memory_id.strip():
            raise ValueError(
                "memory_id cannot be empty."
            )

    def get(
        self,
        memory_id: str,
    ) -> Memory:
        """
        Retrieve a memory by its identifier.

        Parameters
        ----------
        memory_id:
            Memory identifier.

        Returns
        -------
        Memory
            The matching memory.

        Raises
        ------
        MemoryNotFoundError
            If the memory does not exist.
        """

        self._validate_memory_id(
            memory_id=memory_id,
        )

        with self._lock:
            memory = self._storage.get(
                memory_id=memory_id,
            )

            if memory is None:
                raise MemoryNotFoundError(
                    f"Memory '{memory_id}' was not found."
                )

            return memory

    def contains(
        self,
        memory_id: str,
    ) -> bool:
        """
        Determine whether a memory exists.

        Parameters
        ----------
        memory_id:
            Memory identifier.

        Returns
        -------
        bool
            True if the memory exists; otherwise False.
        """

        self._validate_memory_id(
            memory_id=memory_id,
        )

        with self._lock:
            return self._storage.exists(
                memory_id=memory_id,
            )

    def count(self) -> int:
        """
        Return the total number of stored memories.

        Returns
        -------
        int
            Total number of memories.
        """

        with self._lock:
            return self._storage.count()

    def get_all(self) -> tuple[Memory, ...]:
        """
        Retrieve all stored memories.

        Returns
        -------
        tuple[Memory, ...]
            Immutable collection of memories.
        """

        with self._lock:
            return self._storage.get_all()

    def register(
        self,
        memory: Memory,
    ) -> Memory:
        """
        Register a new memory.

        Parameters
        ----------
        memory:
            Memory to register.

        Returns
        -------
        Memory
            The registered memory.

        Raises
        ------
        InvalidMemoryError
            If the memory is invalid.

        MemoryAlreadyExistsError
            If a memory with the same identifier already exists.
        """

        self._validate_memory(
            memory=memory,
        )

        with self._lock:
            if self._storage.exists(
                memory.memory_id,
            ):
                raise MemoryAlreadyExistsError(
                    f"Memory '{memory.memory_id}' already exists."
                )

            memory = self._storage.insert(
                memory=memory,
            )

            self._logger.info(
                "Registered memory '%s'.",
                memory.memory_id,
            )

            self._event_bus.publish(
                event_name="memory.registered",
                payload=MemoryRegisteredEvent(
                    memory=memory,
                ),
            )


            return memory

    def update(
        self,
        memory: Memory,
    ) -> Memory:
        """
        Update an existing memory.

        Parameters
        ----------
        memory:
            Updated memory.

        Returns
        -------
        Memory
            Updated memory.

        Raises
        ------
        InvalidMemoryError
            If the memory is invalid.

        MemoryNotFoundError
            If the memory does not exist.
        """

        self._validate_memory(
            memory=memory,
        )

        with self._lock:
            updated_memory = self._storage.update(
                memory=memory,
            )

            if updated_memory is None:
                raise MemoryNotFoundError(
                    f"Memory '{memory.memory_id}' was not found."
                )

            self._logger.info(
                "Updated memory '%s'.",
                updated_memory.memory_id,
            )

            self._event_bus.publish(
                event_name="memory.updated",
                payload=MemoryUpdatedEvent(
                    memory=updated_memory,
                ),
            )

            return updated_memory

    def remove(
        self,
        memory_id: str,
    ) -> Memory:
        """
        Remove a memory.

        Parameters
        ----------
        memory_id:
            Memory identifier.

        Returns
        -------
        Memory
            Removed memory.

        Raises
        ------
        MemoryNotFoundError
            If the memory does not exist.
        """

        self._validate_memory_id(
            memory_id=memory_id,
        )

        with self._lock:
            removed_memory = self._storage.delete(
                memory_id=memory_id,
            )

            if removed_memory is None:
                raise MemoryNotFoundError(
                    f"Memory '{memory_id}' was not found."
                )

            self._logger.info(
                "Removed memory '%s'.",
                removed_memory.memory_id,
            )

            self._event_bus.publish(
                event_name="memory.removed",
                payload=MemoryRemovedEvent(
                    memory=removed_memory,
                ),
            )

            return removed_memory

    def get_by_scope(
        self,
        scope: MemoryScope,
        session_id: str | None = None,
    ) -> tuple[Memory, ...]:
        """
        Retrieve memories matching a scope, optionally within a session.

        Parameters
        ----------
        scope:
            Scope to filter by.

        session_id:
            Optional session identifier to further filter by.

        Returns
        -------
        tuple[Memory, ...]
            Matching memories, ordered by created_at.
        """

        if type(scope) is not MemoryScope:
            raise TypeError("scope must be a MemoryScope.")

        if session_id is not None and type(session_id) is not str:
            raise TypeError("session_id must be a string or None.")

        with self._lock:
            return self._storage.get_by_scope(
                scope=scope.value, session_id=session_id
            )

    def get_by_kind(self, kind: MemoryKind) -> tuple[Memory, ...]:
        """
        Retrieve memories matching a kind.

        Parameters
        ----------
        kind:
            Kind to filter by.

        Returns
        -------
        tuple[Memory, ...]
            Matching memories, ordered by created_at.
        """

        if type(kind) is not MemoryKind:
            raise TypeError("kind must be a MemoryKind.")

        with self._lock:
            return self._storage.get_by_kind(kind=kind.value)

    def touch(self, memory_id: str) -> Memory:
        """
        Record an access to a memory, bumping its access_count and
        last_accessed_at. Purely mechanical bookkeeping; never
        interprets the memory's content.

        Parameters
        ----------
        memory_id:
            Memory identifier.

        Returns
        -------
        Memory
            The updated memory.

        Raises
        ------
        MemoryNotFoundError
            If the memory does not exist.
        """

        self._validate_memory_id(memory_id=memory_id)

        with self._lock:
            updated = self._storage.touch(
                memory_id=memory_id, accessed_at=datetime.now(UTC)
            )

            if updated is None:
                raise MemoryNotFoundError(
                    f"Memory '{memory_id}' was not found."
                )

            return updated

    def search(self, query: MemorySearchQuery) -> tuple[ScoredMemory, ...]:
        """
        Search memories using deterministic, lexical (FTS5 BM25) ranking
        blended with recency, importance, and access-frequency signals.

        This method never performs semantic search and never generates
        an embedding -- see Core_Component_Responsibilities.md's
        MemoryManager "Does NOT" list.

        Reports its own `memory.search.started/completed/failed`
        execution progress through the already-injected `EventBus`
        (Phase 3.5b), as an independent activity -- never nested under
        any caller's tree; see `docs/architecture/
        Core_Component_Responsibilities.md`'s Execution Progress
        addendum.

        Parameters
        ----------
        query:
            Search query.

        Returns
        -------
        tuple[ScoredMemory, ...]
            Score-ranked, paginated results.

        Raises
        ------
        InvalidMemoryError
            If query is not a MemorySearchQuery.
        """

        if type(query) is not MemorySearchQuery:
            raise InvalidMemoryError("query must be a MemorySearchQuery.")

        progress = ProgressReporter(self._event_bus, "memory.search")
        progress.started()

        try:
            with self._lock:
                results = _lifecycle_search(
                    self._storage, query=query, config=self._config
                )

        except Exception as ex:
            progress.failed(message=str(ex))
            raise

        progress.completed(message=f"{len(results)} result(s).")

        return results

    def consolidation_candidates(
        self, policy: ConsolidationPolicy
    ) -> tuple[Memory, ...]:
        """
        Deterministically select consolidation candidates. Read-only --
        never summarizes or interprets content. The caller (e.g. Brain's
        context_engine) is responsible for turning candidates into a
        SUMMARY memory and calling prune() on the originals; see
        docs/architecture/Intelligence_Foundation_Design.md section 4.3.

        Parameters
        ----------
        policy:
            Deterministic selection criteria.

        Returns
        -------
        tuple[Memory, ...]
            Candidate memories, oldest first.
        """

        if type(policy) is not ConsolidationPolicy:
            raise InvalidMemoryError("policy must be a ConsolidationPolicy.")

        with self._lock:
            return _lifecycle_consolidation_candidates(self._storage, policy=policy)

    def prune(self, policy: PrunePolicy) -> tuple[Memory, ...]:
        """
        Deterministically remove expired and/or excess memories.

        Parameters
        ----------
        policy:
            Deterministic pruning criteria.

        Returns
        -------
        tuple[Memory, ...]
            Memories that were removed.
        """

        if type(policy) is not PrunePolicy:
            raise InvalidMemoryError("policy must be a PrunePolicy.")

        with self._lock:
            return _lifecycle_prune(
                self._storage,
                policy=policy,
                event_bus=self._event_bus,
                logger=self._logger,
            )

    # ------------------------------------------------------------------
    # High-level, duplicate-aware convenience API (Phase 1 Completion
    # Specification section 9). Every one of these methods is a public
    # entry point most callers -- the memory-as-tool capability,
    # `preference_detection.py`, CLI commands -- should prefer over the
    # lower-level `register()`/`remove()` primitives above.
    # ------------------------------------------------------------------

    def remember(
        self,
        *,
        content: str,
        category: MemoryCategory = MemoryCategory.CUSTOM,
        kind: MemoryKind = MemoryKind.FACT,
        origin: MemoryOrigin = MemoryOrigin.USER_EXPLICIT,
        scope: MemoryScope = MemoryScope.GLOBAL,
        session_id: str | None = None,
        importance: MemoryImportance = MemoryImportance.NORMAL,
        importance_score: float | None = None,
        confidence: float = 1.0,
        tags: frozenset[str] = frozenset(),
        metadata: dict[str, object] | None = None,
    ) -> tuple[Memory, bool]:
        """
        Remember a fact, preference, or other piece of information as a
        permanent memory, automatically merging into an existing
        near-duplicate rather than creating a new one (see
        `duplicate_detection.py`).

        Defaults to `scope=GLOBAL` (unlike `register()`'s
        `Memory(scope=SESSION)` default) because a "remembered" fact is,
        by definition, meant to survive and be retrievable across every
        future conversation, not just the current one -- see the Phase 1
        Completion Specification section 1 ("True Permanent Memory").

        Returns
        -------
        tuple[Memory, bool]
            The stored memory, and whether it was newly created (True)
            or merged into an existing duplicate (False).

        Raises
        ------
        InvalidMemoryError
            If `content` is not a non-empty string, or any enum/type
            argument is invalid.
        """

        if type(content) is not str or not content.strip():
            raise InvalidMemoryError("content must be a non-empty string.")

        if type(category) is not MemoryCategory:
            raise InvalidMemoryError("category must be a MemoryCategory.")

        if type(kind) is not MemoryKind:
            raise InvalidMemoryError("kind must be a MemoryKind.")

        if type(origin) is not MemoryOrigin:
            raise InvalidMemoryError("origin must be a MemoryOrigin.")

        if type(scope) is not MemoryScope:
            raise InvalidMemoryError("scope must be a MemoryScope.")

        if type(importance) is not MemoryImportance:
            raise InvalidMemoryError("importance must be a MemoryImportance.")

        with self._lock:
            stored, created = _remember_remember(
                self._storage,
                content=content,
                category=category,
                kind=kind,
                origin=origin,
                scope=scope,
                session_id=session_id,
                importance=importance,
                importance_score=importance_score,
                confidence=confidence,
                tags=tags,
                metadata=metadata or {},
                duplicate_similarity_threshold=DEFAULT_DUPLICATE_SIMILARITY_THRESHOLD,
            )

            self._logger.info(
                "%s permanent memory '%s' (category=%s).",
                "Remembered" if created else "Reinforced existing",
                stored.memory_id,
                stored.category.value,
            )

            self._event_bus.publish(
                event_name=("memory.registered" if created else "memory.updated"),
                payload=(
                    MemoryRegisteredEvent(memory=stored)
                    if created
                    else MemoryUpdatedEvent(memory=stored)
                ),
            )

            return stored, created

    def forget(self, memory_id: str) -> Memory:
        """Alias for `remove()` -- forget a permanent memory by id."""

        return self.remove(memory_id)

    def merge(self, primary_id: str, secondary_id: str) -> Memory:
        """
        Explicitly merge `secondary_id` into `primary_id`: combines
        tags/metadata, keeps the primary's content as canonical, bumps
        confidence, and deletes the secondary memory.

        Raises
        ------
        MemoryNotFoundError
            If either memory does not exist.
        """

        self._validate_memory_id(memory_id=primary_id)
        self._validate_memory_id(memory_id=secondary_id)

        with self._lock:
            merged, deleted_secondary = _remember_merge(
                self._storage, primary_id=primary_id, secondary_id=secondary_id
            )

            self._logger.info(
                "Merged memory '%s' into '%s'.", secondary_id, primary_id
            )

            self._event_bus.publish(
                event_name="memory.updated",
                payload=MemoryUpdatedEvent(memory=merged),
            )
            self._event_bus.publish(
                event_name="memory.removed",
                payload=MemoryRemovedEvent(memory=deleted_secondary),
            )

            return merged

    def list(
        self,
        *,
        category: MemoryCategory | None = None,
        scope: MemoryScope | None = None,
        session_id: str | None = None,
        limit: int | None = None,
    ) -> tuple[Memory, ...]:
        """List memories matching optional filters, newest-updated first."""

        if category is not None and type(category) is not MemoryCategory:
            raise InvalidMemoryError("category must be a MemoryCategory or None.")

        if scope is not None and type(scope) is not MemoryScope:
            raise InvalidMemoryError("scope must be a MemoryScope or None.")

        if limit is not None and (type(limit) is not int or limit <= 0):
            raise InvalidMemoryError("limit must be a positive int or None.")

        with self._lock:
            return _bulk_list_memories(
                self._storage,
                category=category,
                scope=scope,
                session_id=session_id,
                limit=limit,
            )

    def delete(self, memory_id: str) -> Memory:
        """Alias for `remove()`."""

        return self.remove(memory_id)

    def clear(
        self,
        *,
        category: MemoryCategory | None = None,
        scope: MemoryScope | None = None,
        session_id: str | None = None,
    ) -> tuple[Memory, ...]:
        """
        Delete every memory matching the optional filters (no filters
        clears everything). Returns every removed memory.
        """

        if category is not None and type(category) is not MemoryCategory:
            raise InvalidMemoryError("category must be a MemoryCategory or None.")

        if scope is not None and type(scope) is not MemoryScope:
            raise InvalidMemoryError("scope must be a MemoryScope or None.")

        with self._lock:
            return _bulk_clear(
                self._storage,
                category=category,
                scope=scope,
                session_id=session_id,
                event_bus=self._event_bus,
                logger=self._logger,
            )

    def stats(self) -> MemoryStats:
        """Return aggregate statistics over every stored memory."""

        with self._lock:
            return _bulk_stats(self._storage)

    def export(self, path: Path) -> int:
        """
        Export every stored memory to `path` as a JSON array. Returns
        the number of memories exported.
        """

        if not isinstance(path, PurePath):
            raise InvalidMemoryError("path must be a pathlib.Path object.")

        with self._lock:
            return _io_export_memories(self._storage, path=path)

    def import_memories(self, path: Path, *, on_duplicate: str = "skip") -> int:
        """
        Import memories from a JSON file previously produced by
        `export()`. Returns the number of memories inserted/replaced.

        Note: named `import_memories()`, not `import()`, because
        `import` is a reserved Python keyword and cannot be a method
        name.
        """

        if not isinstance(path, PurePath):
            raise InvalidMemoryError("path must be a pathlib.Path object.")

        with self._lock:
            return _io_import_memories(
                self._storage, path=path, on_duplicate=on_duplicate
            )