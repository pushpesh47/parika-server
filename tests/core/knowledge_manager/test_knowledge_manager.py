"""
Unit tests for KnowledgeManager.

KnowledgeManager coordinates KnowledgeSource lifecycle, KnowledgeEngine
registration/resolution (via KnowledgeEngineRegistry), indexing
orchestration, search orchestration, and lifecycle event publication.
It delegates all actual extraction/indexing/search work to registered
KnowledgeEngine implementations and all persistence to a KnowledgeStorage
implementation - both of which are abstract contracts here, so these
tests exercise KnowledgeManager against small local fakes.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from parika.core.event_bus.event_bus import EventBus
from parika.core.knowledge_manager.engine import KnowledgeEngine
from parika.core.knowledge_manager.events import (
    KnowledgeIndexedEvent,
    KnowledgeIndexRemovedEvent,
    KnowledgeSourceRegisteredEvent,
    KnowledgeSourceRemovedEvent,
    KnowledgeSourceUpdatedEvent,
)
from parika.core.knowledge_manager.exceptions import (
    InvalidKnowledgeSourceError,
    KnowledgeEngineAlreadyExistsError,
    KnowledgeEngineNotFoundError,
    KnowledgeIndexError,
    KnowledgeSearchError,
    KnowledgeSourceAlreadyExistsError,
    KnowledgeSourceDisabledError,
    KnowledgeSourceNotFoundError,
)
from parika.core.knowledge_manager.knowledge_manager import KnowledgeManager
from parika.core.knowledge_manager.knowledge_source import KnowledgeSource
from parika.core.knowledge_manager.registry import KnowledgeEngineRegistry
from parika.core.knowledge_manager.search_query import SearchQuery
from parika.core.knowledge_manager.search_result import SearchResult
from parika.core.knowledge_manager.source_kind import KnowledgeSourceKind
from parika.core.knowledge_manager.source_status import (
    KnowledgeSourceStatus,
)
from parika.core.knowledge_manager.knowledge import Knowledge
from parika.core.knowledge_manager.storage import KnowledgeStorage
from parika.core.logger.logger import Logger


def make_source(**overrides: object) -> KnowledgeSource:
    """
    Build a valid KnowledgeSource, allowing individual fields to be
    overridden per test.
    """

    defaults: dict[str, object] = {
        "id": uuid4(),
        "name": "PARIKA source repository",
        "kind": KnowledgeSourceKind.REPOSITORY,
        "location": "/repo/parika",
        "status": KnowledgeSourceStatus.AVAILABLE,
    }
    defaults.update(overrides)

    return KnowledgeSource(**defaults)  # type: ignore[arg-type]


def make_knowledge(**overrides: object) -> Knowledge:
    """
    Build a valid Knowledge unit, allowing individual fields to be
    overridden per test.
    """

    defaults: dict[str, object] = {
        "id": uuid4(),
        "source_id": uuid4(),
        "title": "KnowledgeManager class",
        "content": "Coordinates knowledge source lifecycle.",
        "location": "knowledge_manager.py:45",
    }
    defaults.update(overrides)

    return Knowledge(**defaults)  # type: ignore[arg-type]


class RecordingSubscriber:
    """
    EventBus subscriber that records every payload it receives.
    """

    def __init__(self) -> None:
        self.received: list[Any] = []

    def __call__(self, payload: Any) -> None:
        self.received.append(payload)


class FakeKnowledgeStorage(KnowledgeStorage):
    """
    In-memory KnowledgeStorage implementation used for testing.
    """

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

    def get_many(
        self,
        source_ids: frozenset[UUID],
    ) -> tuple[KnowledgeSource, ...]:
        return tuple(
            source
            for source_id, source in self._sources.items()
            if source_id in source_ids
        )


class FakeKnowledgeEngine(KnowledgeEngine):
    """
    Configurable KnowledgeEngine fake that records every call made to
    it and lets tests inject failures or canned return values.
    """

    def __init__(
        self,
        *,
        supported_kind: KnowledgeSourceKind | None = None,
        index_return: int = 1,
        index_raises: Exception | None = None,
        remove_raises: Exception | None = None,
        search_return: tuple[SearchResult, ...] = (),
        search_raises: Exception | None = None,
    ) -> None:
        self.supported_kind = supported_kind
        self.index_return = index_return
        self.index_raises = index_raises
        self.remove_raises = remove_raises
        self.search_return = search_return
        self.search_raises = search_raises

        self.indexed: list[KnowledgeSource] = []
        self.removed: list[KnowledgeSource] = []
        self.searched: list[
            tuple[tuple[KnowledgeSource, ...], SearchQuery]
        ] = []

    def supports(self, source: KnowledgeSource) -> bool:
        if self.supported_kind is None:
            return True

        return source.kind == self.supported_kind

    def index(self, source: KnowledgeSource) -> int:
        if self.index_raises is not None:
            raise self.index_raises

        self.indexed.append(source)

        return self.index_return

    def remove(self, source: KnowledgeSource) -> None:
        if self.remove_raises is not None:
            raise self.remove_raises

        self.removed.append(source)

    def search(
        self,
        sources: tuple[KnowledgeSource, ...],
        query: SearchQuery,
    ) -> tuple[SearchResult, ...]:
        if self.search_raises is not None:
            raise self.search_raises

        self.searched.append((sources, query))

        return self.search_return


@pytest.fixture
def storage() -> FakeKnowledgeStorage:
    return FakeKnowledgeStorage()


@pytest.fixture
def registry() -> KnowledgeEngineRegistry:
    return KnowledgeEngineRegistry()


@pytest.fixture
def manager(
    storage: FakeKnowledgeStorage,
    registry: KnowledgeEngineRegistry,
    event_bus: EventBus,
    logger: Logger,
) -> KnowledgeManager:
    return KnowledgeManager(
        storage=storage,
        registry=registry,
        event_bus=event_bus,
        logger=logger,
    )


# ---------------------------------------------------------------------
# register_source() / update_source() / remove_source()
# ---------------------------------------------------------------------


class TestSourceLifecycle:
    def test_register_source_success(
        self,
        manager: KnowledgeManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("knowledge.source.registered", subscriber)

        source = make_source()
        manager.register_source(source)

        assert manager.contains_source(source.id)
        assert manager.get_source(source.id) is source
        assert len(subscriber.received) == 1
        event = subscriber.received[0]
        assert isinstance(event, KnowledgeSourceRegisteredEvent)
        assert event.source_id == source.id

    def test_register_source_rejects_invalid_type(
        self,
        manager: KnowledgeManager,
    ) -> None:
        with pytest.raises(InvalidKnowledgeSourceError):
            manager.register_source("not-a-source")  # type: ignore[arg-type]

    def test_register_source_rejects_duplicate(
        self,
        manager: KnowledgeManager,
    ) -> None:
        source = make_source()
        manager.register_source(source)

        with pytest.raises(KnowledgeSourceAlreadyExistsError):
            manager.register_source(source)

    def test_update_source_success(
        self,
        manager: KnowledgeManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("knowledge.source.updated", subscriber)

        source = make_source()
        manager.register_source(source)

        updated = make_source(
            id=source.id,
            name="Renamed source",
            status=KnowledgeSourceStatus.DISABLED,
        )
        manager.update_source(updated)

        assert manager.get_source(source.id).name == "Renamed source"
        assert (
            manager.get_source(source.id).status
            is KnowledgeSourceStatus.DISABLED
        )
        assert len(subscriber.received) == 1
        assert isinstance(
            subscriber.received[0], KnowledgeSourceUpdatedEvent
        )

    def test_update_source_rejects_invalid_type(
        self,
        manager: KnowledgeManager,
    ) -> None:
        with pytest.raises(InvalidKnowledgeSourceError):
            manager.update_source(object())  # type: ignore[arg-type]

    def test_update_source_raises_when_missing(
        self,
        manager: KnowledgeManager,
    ) -> None:
        with pytest.raises(KnowledgeSourceNotFoundError):
            manager.update_source(make_source())

    def test_remove_source_success(
        self,
        manager: KnowledgeManager,
        registry: KnowledgeEngineRegistry,
        event_bus: EventBus,
    ) -> None:
        removed_subscriber = RecordingSubscriber()
        index_removed_subscriber = RecordingSubscriber()
        event_bus.subscribe(
            "knowledge.source.removed", removed_subscriber
        )
        event_bus.subscribe(
            "knowledge.index.removed", index_removed_subscriber
        )

        engine = FakeKnowledgeEngine()
        registry.register(engine)

        source = make_source()
        manager.register_source(source)

        manager.remove_source(source.id)

        assert not manager.contains_source(source.id)
        assert engine.removed == [source]
        assert len(removed_subscriber.received) == 1
        assert isinstance(
            removed_subscriber.received[0], KnowledgeSourceRemovedEvent
        )
        assert len(index_removed_subscriber.received) == 1
        assert isinstance(
            index_removed_subscriber.received[0],
            KnowledgeIndexRemovedEvent,
        )

    def test_remove_source_raises_when_missing(
        self,
        manager: KnowledgeManager,
    ) -> None:
        with pytest.raises(KnowledgeSourceNotFoundError):
            manager.remove_source(uuid4())

    def test_remove_source_raises_when_no_engine_resolves(
        self,
        manager: KnowledgeManager,
    ) -> None:
        source = make_source()
        manager.register_source(source)

        with pytest.raises(KnowledgeEngineNotFoundError):
            manager.remove_source(source.id)

    def test_remove_source_wraps_engine_failure(
        self,
        manager: KnowledgeManager,
        registry: KnowledgeEngineRegistry,
    ) -> None:
        engine = FakeKnowledgeEngine(remove_raises=RuntimeError("boom"))
        registry.register(engine)

        source = make_source()
        manager.register_source(source)

        with pytest.raises(KnowledgeIndexError) as excinfo:
            manager.remove_source(source.id)

        assert isinstance(excinfo.value.__cause__, RuntimeError)
        # A failed removal must not delete the source from storage.
        assert manager.contains_source(source.id)

    def test_get_source_raises_when_missing(
        self,
        manager: KnowledgeManager,
    ) -> None:
        with pytest.raises(KnowledgeSourceNotFoundError):
            manager.get_source(uuid4())

    def test_get_sources_contains_and_count(
        self,
        manager: KnowledgeManager,
    ) -> None:
        first = make_source()
        second = make_source()

        manager.register_source(first)
        manager.register_source(second)

        assert manager.count_sources() == 2
        assert set(manager.get_sources()) == {first, second}
        assert manager.contains_source(first.id)
        assert not manager.contains_source(uuid4())


# ---------------------------------------------------------------------
# register_engine() / unregister_engine()
# ---------------------------------------------------------------------


class TestEngineRegistration:
    def test_register_engine_success(
        self,
        manager: KnowledgeManager,
        registry: KnowledgeEngineRegistry,
    ) -> None:
        engine = FakeKnowledgeEngine()

        manager.register_engine(engine)

        assert registry.contains(engine)
        assert registry.count() == 1

    def test_register_engine_rejects_duplicate(
        self,
        manager: KnowledgeManager,
    ) -> None:
        engine = FakeKnowledgeEngine()
        manager.register_engine(engine)

        with pytest.raises(KnowledgeEngineAlreadyExistsError):
            manager.register_engine(engine)

    def test_unregister_engine_success(
        self,
        manager: KnowledgeManager,
        registry: KnowledgeEngineRegistry,
    ) -> None:
        engine = FakeKnowledgeEngine()
        manager.register_engine(engine)

        manager.unregister_engine(engine)

        assert not registry.contains(engine)

    def test_unregister_engine_raises_when_missing(
        self,
        manager: KnowledgeManager,
    ) -> None:
        with pytest.raises(KnowledgeEngineNotFoundError):
            manager.unregister_engine(FakeKnowledgeEngine())


# ---------------------------------------------------------------------
# index()
# ---------------------------------------------------------------------


class TestIndex:
    def test_index_success(
        self,
        manager: KnowledgeManager,
        registry: KnowledgeEngineRegistry,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("knowledge.indexed", subscriber)

        engine = FakeKnowledgeEngine(index_return=7)
        registry.register(engine)

        source = make_source()
        manager.register_source(source)

        manager.index(source.id)

        assert engine.indexed == [source]
        assert len(subscriber.received) == 1
        event = subscriber.received[0]
        assert isinstance(event, KnowledgeIndexedEvent)
        assert event.source_id == source.id
        assert event.knowledge_count == 7

    def test_index_raises_when_source_missing(
        self,
        manager: KnowledgeManager,
    ) -> None:
        with pytest.raises(KnowledgeSourceNotFoundError):
            manager.index(uuid4())

    def test_index_raises_when_source_disabled(
        self,
        manager: KnowledgeManager,
        registry: KnowledgeEngineRegistry,
    ) -> None:
        registry.register(FakeKnowledgeEngine())

        source = make_source(status=KnowledgeSourceStatus.DISABLED)
        manager.register_source(source)

        with pytest.raises(KnowledgeSourceDisabledError):
            manager.index(source.id)

    def test_index_raises_when_no_engine_resolves(
        self,
        manager: KnowledgeManager,
    ) -> None:
        source = make_source()
        manager.register_source(source)

        with pytest.raises(KnowledgeEngineNotFoundError):
            manager.index(source.id)

    def test_index_wraps_engine_failure(
        self,
        manager: KnowledgeManager,
        registry: KnowledgeEngineRegistry,
    ) -> None:
        engine = FakeKnowledgeEngine(index_raises=RuntimeError("boom"))
        registry.register(engine)

        source = make_source()
        manager.register_source(source)

        with pytest.raises(KnowledgeIndexError) as excinfo:
            manager.index(source.id)

        assert isinstance(excinfo.value.__cause__, RuntimeError)


# ---------------------------------------------------------------------
# search()
# ---------------------------------------------------------------------


class TestSearch:
    def test_search_delegates_to_resolved_engine(
        self,
        manager: KnowledgeManager,
        registry: KnowledgeEngineRegistry,
    ) -> None:
        result = SearchResult(knowledge=make_knowledge(), score=0.9)
        engine = FakeKnowledgeEngine(search_return=(result,))
        registry.register(engine)

        source = make_source()
        manager.register_source(source)

        query = SearchQuery(text="indexing")
        results = manager.search(query)

        assert results == (result,)
        assert len(engine.searched) == 1
        searched_sources, searched_query = engine.searched[0]
        assert searched_sources == (source,)
        assert searched_query is query

    def test_search_restricts_to_requested_source_ids(
        self,
        manager: KnowledgeManager,
        registry: KnowledgeEngineRegistry,
    ) -> None:
        engine = FakeKnowledgeEngine()
        registry.register(engine)

        first = make_source()
        second = make_source()
        manager.register_source(first)
        manager.register_source(second)

        query = SearchQuery(text="indexing", source_ids=frozenset({first.id}))
        manager.search(query)

        searched_sources, _ = engine.searched[0]
        assert searched_sources == (first,)

    def test_search_excludes_disabled_sources_by_default(
        self,
        manager: KnowledgeManager,
        registry: KnowledgeEngineRegistry,
    ) -> None:
        engine = FakeKnowledgeEngine()
        registry.register(engine)

        available = make_source(status=KnowledgeSourceStatus.AVAILABLE)
        disabled = make_source(status=KnowledgeSourceStatus.DISABLED)
        manager.register_source(available)
        manager.register_source(disabled)

        manager.search(SearchQuery(text="indexing"))

        searched_sources, _ = engine.searched[0]
        assert searched_sources == (available,)

    def test_search_includes_disabled_sources_when_requested(
        self,
        manager: KnowledgeManager,
        registry: KnowledgeEngineRegistry,
    ) -> None:
        engine = FakeKnowledgeEngine()
        registry.register(engine)

        available = make_source(status=KnowledgeSourceStatus.AVAILABLE)
        disabled = make_source(status=KnowledgeSourceStatus.DISABLED)
        manager.register_source(available)
        manager.register_source(disabled)

        manager.search(
            SearchQuery(text="indexing", include_disabled=True)
        )

        searched_sources, _ = engine.searched[0]
        assert set(searched_sources) == {available, disabled}

    def test_search_excludes_registered_sources(
        self,
        manager: KnowledgeManager,
        registry: KnowledgeEngineRegistry,
    ) -> None:
        engine = FakeKnowledgeEngine()
        registry.register(engine)

        registered_only = make_source(
            status=KnowledgeSourceStatus.REGISTERED
        )
        manager.register_source(registered_only)

        manager.search(
            SearchQuery(text="indexing", include_disabled=True)
        )

        assert engine.searched == []

    def test_search_raises_when_no_engine_resolves(
        self,
        manager: KnowledgeManager,
    ) -> None:
        source = make_source()
        manager.register_source(source)

        with pytest.raises(KnowledgeEngineNotFoundError):
            manager.search(SearchQuery(text="indexing"))

    def test_search_wraps_engine_failure(
        self,
        manager: KnowledgeManager,
        registry: KnowledgeEngineRegistry,
    ) -> None:
        engine = FakeKnowledgeEngine(search_raises=RuntimeError("boom"))
        registry.register(engine)

        source = make_source()
        manager.register_source(source)

        with pytest.raises(KnowledgeSearchError) as excinfo:
            manager.search(SearchQuery(text="indexing"))

        assert isinstance(excinfo.value.__cause__, RuntimeError)

    def test_search_groups_sources_by_resolved_engine(
        self,
        manager: KnowledgeManager,
        registry: KnowledgeEngineRegistry,
    ) -> None:
        repo_result = SearchResult(knowledge=make_knowledge(), score=0.8)
        docs_result = SearchResult(knowledge=make_knowledge(), score=0.4)

        repo_engine = FakeKnowledgeEngine(
            supported_kind=KnowledgeSourceKind.REPOSITORY,
            search_return=(repo_result,),
        )
        docs_engine = FakeKnowledgeEngine(
            supported_kind=KnowledgeSourceKind.DOCUMENTATION,
            search_return=(docs_result,),
        )
        registry.register(repo_engine)
        registry.register(docs_engine)

        repo_source = make_source(kind=KnowledgeSourceKind.REPOSITORY)
        docs_source = make_source(kind=KnowledgeSourceKind.DOCUMENTATION)
        manager.register_source(repo_source)
        manager.register_source(docs_source)

        results = manager.search(SearchQuery(text="indexing"))

        # SearchResult is unhashable (its `metadata` field is a
        # MappingProxyType), so membership is checked without a set.
        assert len(results) == 2
        assert repo_result in results
        assert docs_result in results
        assert repo_engine.searched[0][0] == (repo_source,)
        assert docs_engine.searched[0][0] == (docs_source,)

    def test_search_with_no_matching_sources_returns_empty(
        self,
        manager: KnowledgeManager,
    ) -> None:
        results = manager.search(SearchQuery(text="indexing"))

        assert results == ()


# ---------------------------------------------------------------------
# KnowledgeEngineRegistry (exercised directly)
# ---------------------------------------------------------------------


class TestKnowledgeEngineRegistry:
    def test_register_and_contains(
        self,
        registry: KnowledgeEngineRegistry,
    ) -> None:
        engine = FakeKnowledgeEngine()

        registry.register(engine)

        assert registry.contains(engine)
        assert registry.count() == 1
        assert registry.get_all() == (engine,)

    def test_register_rejects_duplicate(
        self,
        registry: KnowledgeEngineRegistry,
    ) -> None:
        engine = FakeKnowledgeEngine()
        registry.register(engine)

        with pytest.raises(KnowledgeEngineAlreadyExistsError):
            registry.register(engine)

    def test_unregister_raises_when_missing(
        self,
        registry: KnowledgeEngineRegistry,
    ) -> None:
        with pytest.raises(KnowledgeEngineNotFoundError):
            registry.unregister(FakeKnowledgeEngine())

    def test_resolve_returns_first_supporting_engine(
        self,
        registry: KnowledgeEngineRegistry,
    ) -> None:
        unsupported = FakeKnowledgeEngine(
            supported_kind=KnowledgeSourceKind.DOCUMENTATION
        )
        supported = FakeKnowledgeEngine(
            supported_kind=KnowledgeSourceKind.REPOSITORY
        )
        registry.register(unsupported)
        registry.register(supported)

        source = make_source(kind=KnowledgeSourceKind.REPOSITORY)

        assert registry.resolve(source) is supported

    def test_resolve_raises_when_no_engine_supports(
        self,
        registry: KnowledgeEngineRegistry,
    ) -> None:
        registry.register(
            FakeKnowledgeEngine(
                supported_kind=KnowledgeSourceKind.DOCUMENTATION
            )
        )

        source = make_source(kind=KnowledgeSourceKind.REPOSITORY)

        with pytest.raises(KnowledgeEngineNotFoundError):
            registry.resolve(source)

    def test_clear_removes_all_engines(
        self,
        registry: KnowledgeEngineRegistry,
    ) -> None:
        registry.register(FakeKnowledgeEngine())
        registry.register(FakeKnowledgeEngine())

        registry.clear()

        assert registry.count() == 0
        assert registry.get_all() == ()
