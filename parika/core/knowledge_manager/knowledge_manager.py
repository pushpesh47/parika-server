"""
PARIKA Knowledge Manager

Coordinates the lifecycle of KnowledgeSource objects, knowledge engine
registration, indexing orchestration, search orchestration, lifecycle
event publication, and diagnostic logging.

KnowledgeManager does not implement extraction, indexing, storage,
ranking, or search algorithms. Those responsibilities belong to the
registered KnowledgeEngine implementations and KnowledgeStorage.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime
from threading import RLock
from uuid import UUID

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger

from .engine import KnowledgeEngine
from .events import (
    KnowledgeIndexedEvent,
    KnowledgeIndexRemovedEvent,
    KnowledgeSourceRegisteredEvent,
    KnowledgeSourceRemovedEvent,
    KnowledgeSourceUpdatedEvent,
)
from .exceptions import (
    InvalidKnowledgeSourceError,
    KnowledgeEngineNotFoundError,
    KnowledgeIndexError,
    KnowledgeSearchError,
    KnowledgeSourceAlreadyExistsError,
    KnowledgeSourceDisabledError,
    KnowledgeSourceNotFoundError,
)
from parika.core.utilities.progress import ProgressReporter

from .knowledge_source import KnowledgeSource
from .registry import KnowledgeEngineRegistry
from .search_query import SearchQuery
from .search_result import SearchResult
from .source_status import KnowledgeSourceStatus
from .storage import KnowledgeStorage


class KnowledgeManager:
    """
    Coordinates knowledge source lifecycle, indexing orchestration,
    search orchestration, lifecycle events, and logging.
    """

    def __init__(
        self,
        storage: KnowledgeStorage,
        registry: KnowledgeEngineRegistry,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        """
        Initialize the KnowledgeManager.
        """

        self._storage = storage
        self._registry = registry
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)
        self._lock = RLock()

    def _validate_source(
        self,
        source: KnowledgeSource,
    ) -> None:
        """
        Validate a KnowledgeSource object.
        """

        if type(source) is not KnowledgeSource:
            raise InvalidKnowledgeSourceError(
                "Expected a KnowledgeSource instance."
            )

    def _require_source(
        self,
        source_id: UUID,
    ) -> KnowledgeSource:
        """
        Retrieve an existing KnowledgeSource.
        """

        with self._lock:
            if not self._storage.contains(source_id):
                raise KnowledgeSourceNotFoundError(
                    f"Knowledge source '{source_id}' was not found."
                )

            return self._storage.get(source_id)

    def _require_enabled_source(
        self,
        source: KnowledgeSource,
    ) -> None:
        """
        Ensure the supplied source is available for indexing.
        """

        if source.status is not KnowledgeSourceStatus.AVAILABLE:
            raise KnowledgeSourceDisabledError(
                f"Knowledge source '{source.name}' is not available for indexing."
            )

    def _resolve_engine(
        self,
        source: KnowledgeSource,
    ) -> KnowledgeEngine:
        """
        Resolve the engine responsible for a source.
        """

        return self._registry.resolve(source)

    def register_source(
        self,
        source: KnowledgeSource,
    ) -> None:
        """
        Register a knowledge source.
        """

        with self._lock:
            self._validate_source(source)

            if self._storage.contains(source.id):
                raise KnowledgeSourceAlreadyExistsError(
                    f"Knowledge source '{source.name}' is already registered."
                )

            self._storage.save(source)

            self._event_bus.publish(
                "knowledge.source.registered",
                KnowledgeSourceRegisteredEvent(
                    source_id=source.id,
                ),
            )

            self._logger.debug(
                "Registered knowledge source '%s'.",
                source.name,
            )

    def update_source(
        self,
        source: KnowledgeSource,
    ) -> None:
        """
        Update an existing knowledge source.
        """

        with self._lock:
            self._validate_source(source)

            self._require_source(source.id)

            self._storage.update(source)

            self._event_bus.publish(
                "knowledge.source.updated",
                KnowledgeSourceUpdatedEvent(
                    source_id=source.id,
                ),
            )

            self._logger.debug(
                "Updated knowledge source '%s'.",
                source.name,
            )

    def remove_source(
        self,
        source_id: UUID,
    ) -> None:
        """
        Remove a knowledge source and its index.
        """

        with self._lock:
            source = self._require_source(source_id)

            engine = self._resolve_engine(source)

            try:
                engine.remove(source)
            except Exception as exc:
                raise KnowledgeIndexError(
                    f"Failed to remove knowledge index for source '{source.name}'."
                ) from exc

            self._storage.delete(source.id)

            self._event_bus.publish(
                "knowledge.source.removed",
                KnowledgeSourceRemovedEvent(
                    source_id=source.id,
                ),
            )

            self._event_bus.publish(
                "knowledge.index.removed",
                KnowledgeIndexRemovedEvent(
                    source_id=source.id,
                ),
            )

            self._logger.debug(
                "Removed knowledge source '%s'.",
                source.name,
            )

    def get_source(
        self,
        source_id: UUID,
    ) -> KnowledgeSource:
        """
        Retrieve a knowledge source.
        """

        with self._lock:
            return self._require_source(source_id)

    def get_sources(self) -> tuple[KnowledgeSource, ...]:
        """
        Retrieve all knowledge sources.
        """

        with self._lock:
            return self._storage.get_all()

    def contains_source(
        self,
        source_id: UUID,
    ) -> bool:
        """
        Determine whether a knowledge source exists.
        """

        with self._lock:
            return self._storage.contains(source_id)

    def count_sources(self) -> int:
        """
        Return the number of registered knowledge sources.
        """

        with self._lock:
            return self._storage.count()

    def count_engines(self) -> int:
        """
        Return the number of registered knowledge engines.
        """

        with self._lock:
            return self._registry.count()

    def register_engine(
        self,
        engine: KnowledgeEngine,
    ) -> None:
        """
        Register a knowledge engine.
        """

        with self._lock:
            self._registry.register(engine)

            self._logger.debug(
                "Registered knowledge engine '%s'.",
                type(engine).__name__,
            )

    def unregister_engine(
        self,
        engine: KnowledgeEngine,
    ) -> None:
        """
        Unregister a knowledge engine.
        """

        with self._lock:
            self._registry.unregister(engine)

            self._logger.debug(
                "Unregistered knowledge engine '%s'.",
                type(engine).__name__,
            )

    def index(
        self,
        source_id: UUID,
    ) -> None:
        """
        Index a knowledge source.
        """

        with self._lock:
            source = self._require_source(source_id)

            self._require_enabled_source(source)

            engine = self._resolve_engine(source)

            try:
                knowledge_count = engine.index(source)

            except Exception as exc:
                raise KnowledgeIndexError(
                    f"Failed to index knowledge source '{source.name}'."
                ) from exc

            self._event_bus.publish(
                "knowledge.indexed",
                KnowledgeIndexedEvent(
                    source_id=source.id,
                    knowledge_count=knowledge_count,
                ),
            )

            self._logger.debug(
                "Indexed knowledge source '%s' (%d knowledge units).",
                source.name,
                knowledge_count,
            )

    def index_incremental(
        self,
        source_id: UUID,
        content_hash: str,
    ) -> bool:
        """
        Index a knowledge source only if its content has changed.

        Compares `content_hash` (an opaque string computed by the
        caller/engine -- KnowledgeManager never computes or interprets
        it) against the source's stored `content_hash`. If they match,
        indexing is skipped. If they differ, `index()` runs and the
        source's `content_hash`/`last_indexed_at` are updated.

        This is a purely structural, string-equality comparison -- the
        same category of bookkeeping `_require_enabled_source()` already
        performs by comparing a `status` enum.

        Returns
        -------
        bool
            True if indexing ran; False if it was skipped because the
            content hash was unchanged.
        """

        with self._lock:
            source = self._require_source(source_id)

            if source.content_hash == content_hash:
                self._logger.debug(
                    "Skipping re-index of knowledge source '%s' -- content "
                    "hash unchanged.",
                    source.name,
                )
                return False

            self.index(source_id)

            updated_source = replace(
                source,
                content_hash=content_hash,
                last_indexed_at=datetime.now(UTC),
            )
            self._storage.update(updated_source)

            return True

    def search(
        self,
        query: SearchQuery,
    ) -> tuple[SearchResult, ...]:
        """
        Execute a search across the appropriate knowledge sources.

        Results from every resolved engine are merged, then sorted by
        each result's already-computed score (descending) and paginated
        by `query.limit`/`query.offset`. This is pure bookkeeping over
        values engines already computed -- KnowledgeManager still never
        computes a score itself.

        Reports its own `knowledge.search.started/completed/failed`
        execution progress through the already-injected `EventBus`
        (Phase 3.5b), as an independent activity -- never nested under
        any caller's tree; see `docs/architecture/
        Core_Component_Responsibilities.md`'s Execution Progress
        addendum.
        """

        progress = ProgressReporter(self._event_bus, "knowledge.search")
        progress.started()

        sources: tuple[KnowledgeSource, ...]

        with self._lock:
            if query.source_ids:
                sources = self._storage.get_many(query.source_ids)
            else:
                sources = self._storage.get_all()

        if query.include_disabled:
            searchable_statuses = (
                KnowledgeSourceStatus.AVAILABLE,
                KnowledgeSourceStatus.DISABLED,
            )
        else:
            searchable_statuses = (
                KnowledgeSourceStatus.AVAILABLE,
            )

        sources = tuple(
            source
            for source in sources
            if source.status in searchable_statuses
        )

        grouped_sources: dict[
            KnowledgeEngine,
            list[KnowledgeSource],
        ] = defaultdict(list)

        try:
            for source in sources:
                engine = self._resolve_engine(source)
                grouped_sources[engine].append(source)

            results: list[SearchResult] = []

            for engine, engine_sources in grouped_sources.items():
                results.extend(
                    engine.search(
                        tuple(engine_sources),
                        query,
                    )
                )

        except KnowledgeEngineNotFoundError:
            progress.failed(message="no engine resolved")
            raise
        except Exception as exc:
            progress.failed(message=str(exc))
            raise KnowledgeSearchError(
                "Knowledge search failed."
            ) from exc

        self._logger.debug(
            "Executed knowledge search for '%s'.",
            query.text,
        )

        results.sort(key=lambda result: result.score, reverse=True)

        paginated = tuple(
            results[query.offset : query.offset + query.limit]
        )

        progress.completed(message=f"{len(paginated)} result(s).")

        return paginated