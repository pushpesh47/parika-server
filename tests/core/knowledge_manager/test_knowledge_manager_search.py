"""
Unit tests for KnowledgeManager's Intelligence Foundation extension:
KnowledgeSource content_hash/last_indexed_at, index_incremental(), and
search() sort/paginate bookkeeping.

See docs/architecture/Intelligence_Foundation_Design.md section 5.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from parika.core.event_bus.event_bus import EventBus
from parika.core.knowledge_manager.exceptions import (
    InvalidKnowledgeSourceError,
    KnowledgeEngineNotFoundError,
    KnowledgeSearchError,
    KnowledgeSourceNotFoundError,
)
from parika.core.knowledge_manager.knowledge import Knowledge
from parika.core.knowledge_manager.knowledge_manager import KnowledgeManager
from parika.core.knowledge_manager.knowledge_source import KnowledgeSource
from parika.core.knowledge_manager.registry import KnowledgeEngineRegistry
from parika.core.knowledge_manager.search_query import SearchQuery
from parika.core.knowledge_manager.search_result import SearchResult
from parika.core.knowledge_manager.source_kind import KnowledgeSourceKind
from parika.core.knowledge_manager.source_status import KnowledgeSourceStatus
from parika.core.knowledge_manager.sqlite_storage import SqliteKnowledgeStorage
from parika.core.knowledge_manager.storage import KnowledgeStorage
from parika.core.logger.logger import Logger


def make_source(**overrides: object) -> KnowledgeSource:
    """Build a valid KnowledgeSource, allowing field overrides."""

    defaults: dict[str, object] = {
        "id": uuid4(),
        "name": "PARIKA source repository",
        "kind": KnowledgeSourceKind.REPOSITORY,
        "location": "/repo/parika",
        "status": KnowledgeSourceStatus.AVAILABLE,
    }
    defaults.update(overrides)

    return KnowledgeSource(**defaults)  # type: ignore[arg-type]


class FakeKnowledgeStorage(KnowledgeStorage):
    """In-memory KnowledgeStorage implementation used for testing."""

    def __init__(self) -> None:
        self._sources: dict[UUID, KnowledgeSource] = {}

    def save(self, source: KnowledgeSource) -> None:
        self._sources[source.id] = source

    def update(self, source: KnowledgeSource) -> None:
        self._sources[source.id] = source

    def delete(self, source_id: UUID) -> None:
        self._sources.pop(source_id, None)

    def get(self, source_id: UUID) -> KnowledgeSource:
        return self._sources[source_id]

    def contains(self, source_id: UUID) -> bool:
        return source_id in self._sources

    def get_all(self) -> tuple[KnowledgeSource, ...]:
        return tuple(self._sources.values())

    def count(self) -> int:
        return len(self._sources)

    def get_many(self, source_ids: frozenset[UUID]) -> tuple[KnowledgeSource, ...]:
        return tuple(
            source
            for source_id, source in self._sources.items()
            if source_id in source_ids
        )


class FakeKnowledgeEngine:
    """Minimal configurable KnowledgeEngine fake for these tests."""

    def __init__(
        self,
        *,
        index_return: int = 1,
        search_return: tuple[SearchResult, ...] = (),
    ) -> None:
        self.index_return = index_return
        self.search_return = search_return
        self.indexed: list[KnowledgeSource] = []

    def supports(self, source: KnowledgeSource) -> bool:
        return True

    def index(self, source: KnowledgeSource) -> int:
        self.indexed.append(source)
        return self.index_return

    def remove(self, source: KnowledgeSource) -> None:
        return None

    def search(
        self, sources: tuple[KnowledgeSource, ...], query: SearchQuery
    ) -> tuple[SearchResult, ...]:
        return self.search_return


class TestKnowledgeSourceIncrementalFields:
    def test_defaults(self) -> None:
        source = make_source()

        assert source.content_hash is None
        assert source.last_indexed_at is None

    def test_accepts_values(self) -> None:
        now = datetime.now(UTC)
        source = make_source(content_hash="abc123", last_indexed_at=now)

        assert source.content_hash == "abc123"
        assert source.last_indexed_at == now

    def test_rejects_empty_content_hash(self) -> None:
        with pytest.raises(InvalidKnowledgeSourceError):
            make_source(content_hash="   ")

    def test_rejects_non_datetime_last_indexed_at(self) -> None:
        with pytest.raises(InvalidKnowledgeSourceError):
            make_source(last_indexed_at="not-a-datetime")


class TestIndexIncremental:
    def test_indexes_when_hash_differs(self, logger: Logger, event_bus: EventBus) -> None:
        storage = FakeKnowledgeStorage()
        registry = KnowledgeEngineRegistry()
        engine = FakeKnowledgeEngine()
        registry.register(engine)

        source = make_source()
        storage.save(source)

        manager = KnowledgeManager(
            storage=storage,
            registry=registry,
            event_bus=event_bus,
            logger=logger,
        )

        ran = manager.index_incremental(source.id, "hash-1")

        assert ran is True
        assert len(engine.indexed) == 1

        updated = storage.get(source.id)
        assert updated.content_hash == "hash-1"
        assert updated.last_indexed_at is not None

    def test_skips_when_hash_unchanged(self, logger: Logger, event_bus: EventBus) -> None:
        storage = FakeKnowledgeStorage()
        registry = KnowledgeEngineRegistry()
        engine = FakeKnowledgeEngine()
        registry.register(engine)

        source = make_source(content_hash="hash-1")
        storage.save(source)

        manager = KnowledgeManager(
            storage=storage,
            registry=registry,
            event_bus=event_bus,
            logger=logger,
        )

        ran = manager.index_incremental(source.id, "hash-1")

        assert ran is False
        assert len(engine.indexed) == 0

    def test_raises_when_source_missing(self, logger: Logger, event_bus: EventBus) -> None:
        storage = FakeKnowledgeStorage()
        registry = KnowledgeEngineRegistry()

        manager = KnowledgeManager(
            storage=storage,
            registry=registry,
            event_bus=event_bus,
            logger=logger,
        )

        with pytest.raises(KnowledgeSourceNotFoundError):
            manager.index_incremental(uuid4(), "hash-1")


class TestSearchSortAndPaginate:
    def test_sorts_by_score_descending(self, logger: Logger, event_bus: EventBus) -> None:
        storage = FakeKnowledgeStorage()
        registry = KnowledgeEngineRegistry()

        low = make_source(name="low")
        high = make_source(name="high")
        storage.save(low)
        storage.save(high)

        low_result = SearchResult(knowledge=_make_knowledge(low.id), score=1.0)
        high_result = SearchResult(knowledge=_make_knowledge(high.id), score=9.0)

        engine = FakeKnowledgeEngine(search_return=(low_result, high_result))
        registry.register(engine)

        manager = KnowledgeManager(
            storage=storage,
            registry=registry,
            event_bus=event_bus,
            logger=logger,
        )

        results = manager.search(SearchQuery(text="anything", limit=10))

        assert [r.score for r in results] == [9.0, 1.0]

    def test_paginates_by_limit_and_offset(self, logger: Logger, event_bus: EventBus) -> None:
        storage = FakeKnowledgeStorage()
        registry = KnowledgeEngineRegistry()
        source = make_source()
        storage.save(source)

        results = tuple(
            SearchResult(knowledge=_make_knowledge(source.id), score=float(i))
            for i in range(5)
        )
        engine = FakeKnowledgeEngine(search_return=results)
        registry.register(engine)

        manager = KnowledgeManager(
            storage=storage,
            registry=registry,
            event_bus=event_bus,
            logger=logger,
        )

        page = manager.search(SearchQuery(text="anything", limit=2, offset=1))

        assert [r.score for r in page] == [3.0, 2.0]


class TestSearchProgressReporting:
    """
    Phase 3.5b: `search()` reports its own `knowledge.search.*`
    execution progress, as an independent activity, through the
    already-injected `EventBus`.
    """

    def test_successful_search_publishes_started_and_completed(
        self, logger: Logger, event_bus: EventBus
    ) -> None:
        storage = FakeKnowledgeStorage()
        registry = KnowledgeEngineRegistry()
        source = make_source()
        storage.save(source)

        result = SearchResult(knowledge=_make_knowledge(source.id), score=1.0)
        engine = FakeKnowledgeEngine(search_return=(result,))
        registry.register(engine)

        manager = KnowledgeManager(
            storage=storage, registry=registry, event_bus=event_bus, logger=logger
        )

        events: list[object] = []
        event_bus.subscribe("progress.started", events.append)
        event_bus.subscribe("progress.completed", events.append)
        event_bus.subscribe("progress.failed", events.append)

        manager.search(SearchQuery(text="anything", limit=10))

        source_ids = [event.source_id for event in events]
        assert source_ids == ["knowledge.search", "knowledge.search"]
        assert events[0].stage.value == "started"
        assert events[1].stage.value == "completed"
        assert events[0].progress_id == events[1].progress_id

    def test_engine_failure_publishes_failed(
        self, logger: Logger, event_bus: EventBus
    ) -> None:
        class _FailingEngine(FakeKnowledgeEngine):
            def search(
                self,
                sources: tuple[KnowledgeSource, ...],
                query: SearchQuery,
            ) -> tuple[SearchResult, ...]:
                raise RuntimeError("engine exploded")

        storage = FakeKnowledgeStorage()
        registry = KnowledgeEngineRegistry()
        source = make_source()
        storage.save(source)
        registry.register(_FailingEngine())

        manager = KnowledgeManager(
            storage=storage, registry=registry, event_bus=event_bus, logger=logger
        )

        events: list[object] = []
        event_bus.subscribe("progress.started", events.append)
        event_bus.subscribe("progress.completed", events.append)
        event_bus.subscribe("progress.failed", events.append)

        with pytest.raises(KnowledgeSearchError):
            manager.search(SearchQuery(text="anything", limit=10))

        source_ids_and_stages = [
            (event.source_id, event.stage.value) for event in events
        ]
        assert source_ids_and_stages == [
            ("knowledge.search", "started"),
            ("knowledge.search", "failed"),
        ]

    def test_unresolvable_engine_before_the_search_loop_publishes_failed(
        self, logger: Logger, event_bus: EventBus
    ) -> None:
        """
        Audit report fix: `_resolve_engine()` (called while grouping
        sources, *before* the engine-search `try` block) previously
        raised `KnowledgeEngineNotFoundError` with `started()` already
        published and no matching terminal event -- a confirmed
        lifecycle leak distinct from the engine-failure case above.
        `search()` now reports `progress.failed()` for this path too,
        while still raising the exact same exception type unwrapped.
        """

        storage = FakeKnowledgeStorage()
        registry = KnowledgeEngineRegistry()  # no engine registered
        source = make_source()
        storage.save(source)

        manager = KnowledgeManager(
            storage=storage, registry=registry, event_bus=event_bus, logger=logger
        )

        events: list[object] = []
        event_bus.subscribe("progress.started", events.append)
        event_bus.subscribe("progress.completed", events.append)
        event_bus.subscribe("progress.failed", events.append)

        with pytest.raises(KnowledgeEngineNotFoundError):
            manager.search(SearchQuery(text="anything", limit=10))

        source_ids_and_stages = [
            (event.source_id, event.stage.value) for event in events
        ]
        assert source_ids_and_stages == [
            ("knowledge.search", "started"),
            ("knowledge.search", "failed"),
        ]


class TestSqliteKnowledgeStorage:
    @pytest.fixture
    def storage(self, tmp_path: Path) -> Iterator[SqliteKnowledgeStorage]:
        storage = SqliteKnowledgeStorage(tmp_path / "knowledge.db")
        storage.initialize()

        yield storage

        storage.shutdown()

    def test_round_trips_a_source(self, storage: SqliteKnowledgeStorage) -> None:
        source = make_source(content_hash="hash-1")

        storage.save(source)

        fetched = storage.get(source.id)

        assert fetched.id == source.id
        assert fetched.name == source.name
        assert fetched.kind == source.kind
        assert fetched.content_hash == "hash-1"

    def test_contains_count_and_get_all(self, storage: SqliteKnowledgeStorage) -> None:
        first = make_source(name="first")
        second = make_source(name="second")

        storage.save(first)
        storage.save(second)

        assert storage.contains(first.id) is True
        assert storage.count() == 2
        assert {s.id for s in storage.get_all()} == {first.id, second.id}

    def test_update_persists_changes(self, storage: SqliteKnowledgeStorage) -> None:
        source = make_source()
        storage.save(source)

        updated = make_source(
            id=source.id,
            name=source.name,
            kind=source.kind,
            location=source.location,
            status=KnowledgeSourceStatus.DISABLED,
            content_hash="new-hash",
        )
        storage.update(updated)

        fetched = storage.get(source.id)
        assert fetched.status is KnowledgeSourceStatus.DISABLED
        assert fetched.content_hash == "new-hash"

    def test_delete_removes_source(self, storage: SqliteKnowledgeStorage) -> None:
        source = make_source()
        storage.save(source)

        storage.delete(source.id)

        assert storage.contains(source.id) is False

    def test_get_many_filters_by_id(self, storage: SqliteKnowledgeStorage) -> None:
        first = make_source(name="first")
        second = make_source(name="second")
        storage.save(first)
        storage.save(second)

        results = storage.get_many(frozenset({first.id}))

        assert {s.id for s in results} == {first.id}

    def test_get_many_empty_set_returns_empty(
        self, storage: SqliteKnowledgeStorage
    ) -> None:
        assert storage.get_many(frozenset()) == ()

    def test_reinitializing_is_idempotent(self, storage: SqliteKnowledgeStorage) -> None:
        source = make_source()
        storage.save(source)

        # Re-running initialize() on an already-open connection is a no-op.
        storage.initialize()

        assert storage.contains(source.id) is True


def _make_knowledge(source_id: UUID) -> Knowledge:
    return Knowledge(
        id=uuid4(),
        source_id=source_id,
        title="Title",
        content="Content",
        location="loc",
    )
