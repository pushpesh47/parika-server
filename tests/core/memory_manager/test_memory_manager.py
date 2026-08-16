"""
Unit tests for MemoryManager.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.memory_manager.events import (
    MemoryRegisteredEvent,
    MemoryRemovedEvent,
    MemoryUpdatedEvent,
)
from parika.core.memory_manager.exceptions import (
    InvalidMemoryError,
    MemoryAlreadyExistsError,
    MemoryNotFoundError,
    MemoryPersistenceError,
)
from parika.core.memory_manager.memory import Memory
from parika.core.memory_manager.memory_kind import MemoryKind
from parika.core.memory_manager.memory_manager import MemoryManager
from parika.core.memory_manager.memory_origin import MemoryOrigin


class RecordingSubscriber:
    def __init__(self) -> None:
        self.received: list[Any] = []

    def __call__(self, payload: Any) -> None:
        self.received.append(payload)


def _make_memory(
    *,
    memory_id: str = "memory-1",
    kind: MemoryKind = MemoryKind.FACT,
    origin: MemoryOrigin = MemoryOrigin.USER_EXPLICIT,
    content: str = "The sky is blue.",
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    tags: frozenset[str] = frozenset(),
    metadata: MappingProxyType[str, Any] = MappingProxyType({}),
) -> Memory:
    now = datetime.now(UTC)

    return Memory(
        memory_id=memory_id,
        kind=kind,
        origin=origin,
        content=content,
        created_at=created_at if created_at is not None else now,
        updated_at=updated_at if updated_at is not None else now,
        tags=tags,
        metadata=metadata,
    )


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "memory.db"


@pytest.fixture
def memory_manager(
    logger: Logger,
    event_bus: EventBus,
    database_path: Path,
) -> Iterator[MemoryManager]:
    manager = MemoryManager(
        logger=logger,
        event_bus=event_bus,
        database_path=database_path,
    )
    manager.initialize()

    yield manager

    manager.shutdown()


# ---------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------


class TestConstruction:
    def test_rejects_non_logger(
        self,
        event_bus: EventBus,
        database_path: Path,
    ) -> None:
        with pytest.raises(TypeError):
            MemoryManager(
                logger="not-a-logger",  # type: ignore[arg-type]
                event_bus=event_bus,
                database_path=database_path,
            )

    def test_rejects_non_event_bus(
        self,
        logger: Logger,
        database_path: Path,
    ) -> None:
        with pytest.raises(TypeError):
            MemoryManager(
                logger=logger,
                event_bus="not-an-event-bus",  # type: ignore[arg-type]
                database_path=database_path,
            )

    def test_rejects_non_path_database_path(
        self,
        logger: Logger,
        event_bus: EventBus,
    ) -> None:
        with pytest.raises(TypeError):
            MemoryManager(
                logger=logger,
                event_bus=event_bus,
                database_path="not-a-path",  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------
# initialize() / shutdown()
# ---------------------------------------------------------------------


class TestInitializeAndShutdown:
    def test_initialize_is_idempotent(
        self,
        logger: Logger,
        event_bus: EventBus,
        database_path: Path,
    ) -> None:
        manager = MemoryManager(
            logger=logger,
            event_bus=event_bus,
            database_path=database_path,
        )

        manager.initialize()
        manager.initialize()  # Should not raise.

        manager.shutdown()

    def test_operations_fail_before_initialize(
        self,
        logger: Logger,
        event_bus: EventBus,
        database_path: Path,
    ) -> None:
        manager = MemoryManager(
            logger=logger,
            event_bus=event_bus,
            database_path=database_path,
        )

        with pytest.raises(MemoryPersistenceError):
            manager.count()

    def test_shutdown_before_initialize_is_a_no_op(
        self,
        logger: Logger,
        event_bus: EventBus,
        database_path: Path,
    ) -> None:
        manager = MemoryManager(
            logger=logger,
            event_bus=event_bus,
            database_path=database_path,
        )

        manager.shutdown()  # Should not raise.

    def test_creates_database_file_on_initialize(
        self,
        memory_manager: MemoryManager,
        database_path: Path,
    ) -> None:
        assert database_path.exists()


# ---------------------------------------------------------------------
# register()
# ---------------------------------------------------------------------


class TestRegister:
    def test_registers_memory(
        self,
        memory_manager: MemoryManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("memory.registered", subscriber)

        memory = _make_memory()
        registered = memory_manager.register(memory)

        assert registered == memory
        assert memory_manager.contains("memory-1")
        assert len(subscriber.received) == 1
        assert isinstance(subscriber.received[0], MemoryRegisteredEvent)
        assert subscriber.received[0].memory == memory

    def test_rejects_non_memory(
        self,
        memory_manager: MemoryManager,
    ) -> None:
        with pytest.raises(InvalidMemoryError):
            memory_manager.register("not-a-memory")  # type: ignore[arg-type]

    def test_rejects_duplicate_id(
        self,
        memory_manager: MemoryManager,
    ) -> None:
        memory_manager.register(_make_memory(memory_id="dup"))

        with pytest.raises(MemoryAlreadyExistsError):
            memory_manager.register(_make_memory(memory_id="dup"))

    def test_registered_memory_is_persisted(
        self,
        memory_manager: MemoryManager,
    ) -> None:
        memory_manager.register(_make_memory(memory_id="persisted"))

        stored = memory_manager.get("persisted")

        assert stored.memory_id == "persisted"


# ---------------------------------------------------------------------
# get()
# ---------------------------------------------------------------------


class TestGet:
    def test_returns_stored_memory(
        self,
        memory_manager: MemoryManager,
    ) -> None:
        memory_manager.register(
            _make_memory(memory_id="a", content="Hello")
        )

        retrieved = memory_manager.get("a")

        assert retrieved.content == "Hello"

    def test_raises_when_missing(
        self,
        memory_manager: MemoryManager,
    ) -> None:
        with pytest.raises(MemoryNotFoundError):
            memory_manager.get("missing")

    def test_rejects_non_string_id(
        self,
        memory_manager: MemoryManager,
    ) -> None:
        with pytest.raises(TypeError):
            memory_manager.get(123)  # type: ignore[arg-type]

    def test_rejects_empty_id(
        self,
        memory_manager: MemoryManager,
    ) -> None:
        with pytest.raises(ValueError):
            memory_manager.get("   ")


# ---------------------------------------------------------------------
# contains()
# ---------------------------------------------------------------------


class TestContains:
    def test_true_when_present(
        self,
        memory_manager: MemoryManager,
    ) -> None:
        memory_manager.register(_make_memory(memory_id="a"))

        assert memory_manager.contains("a") is True

    def test_false_when_absent(
        self,
        memory_manager: MemoryManager,
    ) -> None:
        assert memory_manager.contains("missing") is False

    def test_rejects_invalid_id(
        self,
        memory_manager: MemoryManager,
    ) -> None:
        with pytest.raises(ValueError):
            memory_manager.contains("")


# ---------------------------------------------------------------------
# count()
# ---------------------------------------------------------------------


class TestCount:
    def test_zero_when_empty(
        self,
        memory_manager: MemoryManager,
    ) -> None:
        assert memory_manager.count() == 0

    def test_reflects_registered_memories(
        self,
        memory_manager: MemoryManager,
    ) -> None:
        memory_manager.register(_make_memory(memory_id="a"))
        memory_manager.register(_make_memory(memory_id="b"))

        assert memory_manager.count() == 2

    def test_decrements_after_removal(
        self,
        memory_manager: MemoryManager,
    ) -> None:
        memory_manager.register(_make_memory(memory_id="a"))
        memory_manager.remove("a")

        assert memory_manager.count() == 0


# ---------------------------------------------------------------------
# get_all()
# ---------------------------------------------------------------------


class TestGetAll:
    def test_empty_when_no_memories(
        self,
        memory_manager: MemoryManager,
    ) -> None:
        assert memory_manager.get_all() == ()

    def test_returns_all_registered_memories(
        self,
        memory_manager: MemoryManager,
    ) -> None:
        memory_manager.register(_make_memory(memory_id="a"))
        memory_manager.register(_make_memory(memory_id="b"))

        all_memories = memory_manager.get_all()

        assert {memory.memory_id for memory in all_memories} == {"a", "b"}

    def test_ordered_by_created_at(
        self,
        memory_manager: MemoryManager,
    ) -> None:
        earlier = datetime.now(UTC)
        later = earlier + timedelta(seconds=10)

        memory_manager.register(
            _make_memory(
                memory_id="second",
                created_at=later,
                updated_at=later,
            )
        )
        memory_manager.register(
            _make_memory(
                memory_id="first",
                created_at=earlier,
                updated_at=earlier,
            )
        )

        all_memories = memory_manager.get_all()

        assert [memory.memory_id for memory in all_memories] == [
            "first",
            "second",
        ]


# ---------------------------------------------------------------------
# update()
# ---------------------------------------------------------------------


class TestUpdate:
    def test_updates_existing_memory(
        self,
        memory_manager: MemoryManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("memory.updated", subscriber)

        original = _make_memory(memory_id="a", content="Original")
        memory_manager.register(original)

        updated = _make_memory(
            memory_id="a",
            content="Revised",
            created_at=original.created_at,
            updated_at=original.updated_at + timedelta(seconds=1),
        )
        result = memory_manager.update(updated)

        assert result.content == "Revised"
        assert memory_manager.get("a").content == "Revised"
        assert len(subscriber.received) == 1
        assert isinstance(subscriber.received[0], MemoryUpdatedEvent)
        assert subscriber.received[0].memory == updated

    def test_raises_when_missing(
        self,
        memory_manager: MemoryManager,
    ) -> None:
        with pytest.raises(MemoryNotFoundError):
            memory_manager.update(_make_memory(memory_id="missing"))

    def test_rejects_non_memory(
        self,
        memory_manager: MemoryManager,
    ) -> None:
        with pytest.raises(InvalidMemoryError):
            memory_manager.update("not-a-memory")  # type: ignore[arg-type]

    def test_replaces_immutable_record_under_same_id(
        self,
        memory_manager: MemoryManager,
    ) -> None:
        # Memory is an immutable value object: "updating" a memory means
        # replacing the stored record for that id with a brand new Memory
        # instance rather than mutating fields on the existing one.
        original = _make_memory(memory_id="a", tags=frozenset({"x"}))
        memory_manager.register(original)

        replacement = _make_memory(
            memory_id="a",
            tags=frozenset({"y", "z"}),
            created_at=original.created_at,
            updated_at=original.updated_at + timedelta(seconds=1),
        )
        memory_manager.update(replacement)

        stored = memory_manager.get("a")

        assert stored.tags == frozenset({"y", "z"})
        assert stored is not original


# ---------------------------------------------------------------------
# remove()
# ---------------------------------------------------------------------


class TestRemove:
    def test_removes_existing_memory(
        self,
        memory_manager: MemoryManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("memory.removed", subscriber)

        memory_manager.register(_make_memory(memory_id="a"))
        removed = memory_manager.remove("a")

        assert removed.memory_id == "a"
        assert not memory_manager.contains("a")
        assert len(subscriber.received) == 1
        assert isinstance(subscriber.received[0], MemoryRemovedEvent)
        assert subscriber.received[0].memory.memory_id == "a"

    def test_raises_when_missing(
        self,
        memory_manager: MemoryManager,
    ) -> None:
        with pytest.raises(MemoryNotFoundError):
            memory_manager.remove("missing")

    def test_rejects_invalid_id(
        self,
        memory_manager: MemoryManager,
    ) -> None:
        with pytest.raises(ValueError):
            memory_manager.remove("")


# ---------------------------------------------------------------------
# Memory value object
# ---------------------------------------------------------------------


class TestMemory:
    def test_valid_memory_constructs(self) -> None:
        memory = _make_memory()

        assert memory.memory_id == "memory-1"

    def test_rejects_empty_memory_id(self) -> None:
        with pytest.raises(ValueError):
            _make_memory(memory_id="   ")

    def test_rejects_non_string_memory_id(self) -> None:
        with pytest.raises(TypeError):
            Memory(
                memory_id=123,  # type: ignore[arg-type]
                kind=MemoryKind.FACT,
                origin=MemoryOrigin.USER_EXPLICIT,
                content="content",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )

    def test_rejects_invalid_kind(self) -> None:
        with pytest.raises(TypeError):
            Memory(
                memory_id="a",
                kind="fact",  # type: ignore[arg-type]
                origin=MemoryOrigin.USER_EXPLICIT,
                content="content",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )

    def test_rejects_invalid_origin(self) -> None:
        with pytest.raises(TypeError):
            Memory(
                memory_id="a",
                kind=MemoryKind.FACT,
                origin="user_explicit",  # type: ignore[arg-type]
                content="content",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )

    def test_rejects_empty_content(self) -> None:
        with pytest.raises(ValueError):
            _make_memory(content="   ")

    def test_rejects_updated_at_before_created_at(self) -> None:
        now = datetime.now(UTC)

        with pytest.raises(ValueError):
            _make_memory(
                created_at=now,
                updated_at=now - timedelta(seconds=1),
            )

    def test_allows_updated_at_equal_to_created_at(self) -> None:
        now = datetime.now(UTC)

        memory = _make_memory(created_at=now, updated_at=now)

        assert memory.updated_at == memory.created_at

    def test_rejects_non_frozenset_tags(self) -> None:
        with pytest.raises(TypeError):
            _make_memory(tags={"a", "b"})  # type: ignore[arg-type]

    def test_rejects_non_string_tag(self) -> None:
        with pytest.raises(TypeError):
            _make_memory(tags=frozenset({1, 2}))  # type: ignore[arg-type]

    def test_rejects_empty_tag(self) -> None:
        with pytest.raises(ValueError):
            _make_memory(tags=frozenset({"valid", "   "}))

    def test_rejects_non_mapping_proxy_metadata(self) -> None:
        with pytest.raises(TypeError):
            _make_memory(metadata={"key": "value"})  # type: ignore[arg-type]

    def test_metadata_is_defensively_copied(self) -> None:
        source: dict[str, Any] = {"key": "value"}
        proxy = MappingProxyType(source)

        memory = _make_memory(metadata=proxy)
        source["key"] = "mutated"

        assert memory.metadata["key"] == "value"

    def test_default_tags_and_metadata(self) -> None:
        memory = Memory(
            memory_id="a",
            kind=MemoryKind.FACT,
            origin=MemoryOrigin.USER_EXPLICIT,
            content="content",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        assert memory.tags == frozenset()
        assert dict(memory.metadata) == {}

    def test_is_frozen(self) -> None:
        memory = _make_memory()

        with pytest.raises(AttributeError):
            memory.content = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_access_from_other_threads_works_with_check_same_thread_false(
        self,
        memory_manager: MemoryManager,
    ) -> None:
        """
        Verifies that cross-thread access now works correctly.
        MemoryStorage opens its SQLite connection with `check_same_thread=False`,
        and the internal RLock serializes concurrent access from multiple threads.
        """
        errors: list[BaseException] = []

        def _register() -> None:
            try:
                memory_manager.register(
                    _make_memory(memory_id="from-other-thread")
                )
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        thread = threading.Thread(target=_register)
        thread.start()
        thread.join()

        assert len(errors) == 0, f"Expected no errors, got: {errors}"
        assert memory_manager.contains("from-other-thread")

    def test_rlock_allows_reentrant_calls_from_the_same_thread(
        self,
        memory_manager: MemoryManager,
        event_bus: EventBus,
    ) -> None:
        """
        The internal RLock is re-entrant: a synchronous event
        subscriber invoked from within `register()` (still on the
        registering thread, while the lock is held) can safely call
        back into the manager without deadlocking.
        """
        observed_counts: list[int] = []

        def _on_registered(_: Any) -> None:
            observed_counts.append(memory_manager.count())

        event_bus.subscribe("memory.registered", _on_registered)

        memory_manager.register(_make_memory(memory_id="a"))

        assert observed_counts == [1]
