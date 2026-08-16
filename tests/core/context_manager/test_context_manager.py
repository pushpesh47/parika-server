"""
Unit tests for ContextManager and Context.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Any

import pytest

from parika.core.context_manager.context import Context
from parika.core.context_manager.context_manager import ContextManager
from parika.core.context_manager.context_status import ContextStatus
from parika.core.context_manager.context_type import ContextType
from parika.core.context_manager.events import (
    ContextRegistered,
    ContextRemoved,
    ContextUpdated,
)
from parika.core.context_manager.exceptions import (
    ContextAlreadyExistsError,
    ContextNotFoundError,
    InvalidContextError,
)
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger


class RecordingSubscriber:
    def __init__(self) -> None:
        self.received: list[Any] = []

    def __call__(self, payload: Any) -> None:
        self.received.append(payload)


def _make_context(
    *,
    context_id: str = "ctx-1",
    context_type: ContextType = ContextType.TASK,
    status: ContextStatus = ContextStatus.ACTIVE,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    metadata: MappingProxyType[str, Any] | None = None,
) -> Context:
    moment = created_at if created_at is not None else datetime(2024, 1, 1, 12, 0, 0)

    return Context(
        context_id=context_id,
        context_type=context_type,
        status=status,
        created_at=moment,
        updated_at=updated_at if updated_at is not None else moment,
        metadata=metadata if metadata is not None else MappingProxyType({}),
    )


@pytest.fixture
def context_manager(event_bus: EventBus, logger: Logger) -> ContextManager:
    return ContextManager(event_bus=event_bus, logger=logger)


# ---------------------------------------------------------------------
# Context (value object) construction and validation
# ---------------------------------------------------------------------


class TestContext:
    def test_valid_context_constructs(self) -> None:
        context = _make_context(context_id="ctx-1")

        assert context.context_id == "ctx-1"
        assert context.context_type is ContextType.TASK
        assert context.status is ContextStatus.ACTIVE

    def test_metadata_defaults_to_empty_mapping(self) -> None:
        context = _make_context()

        assert dict(context.metadata) == {}

    def test_rejects_non_string_id(self) -> None:
        with pytest.raises(TypeError):
            _make_context(context_id=123)  # type: ignore[arg-type]

    def test_rejects_empty_id(self) -> None:
        with pytest.raises(ValueError):
            _make_context(context_id="")

    def test_rejects_whitespace_only_id(self) -> None:
        with pytest.raises(ValueError):
            _make_context(context_id="   ")

    def test_rejects_invalid_context_type(self) -> None:
        with pytest.raises(TypeError):
            _make_context(context_type="task")  # type: ignore[arg-type]

    def test_rejects_invalid_status(self) -> None:
        with pytest.raises(TypeError):
            _make_context(status="active")  # type: ignore[arg-type]

    def test_rejects_non_datetime_created_at(self) -> None:
        with pytest.raises(TypeError):
            _make_context(created_at="2024-01-01")  # type: ignore[arg-type]

    def test_rejects_non_datetime_updated_at(self) -> None:
        moment = datetime(2024, 1, 1, 12, 0, 0)

        with pytest.raises(TypeError):
            _make_context(
                created_at=moment,
                updated_at="2024-01-01",  # type: ignore[arg-type]
            )

    def test_rejects_updated_at_before_created_at(self) -> None:
        moment = datetime(2024, 1, 1, 12, 0, 0)

        with pytest.raises(ValueError):
            _make_context(
                created_at=moment,
                updated_at=moment - timedelta(seconds=1),
            )

    def test_accepts_updated_at_equal_to_created_at(self) -> None:
        moment = datetime(2024, 1, 1, 12, 0, 0)

        context = _make_context(created_at=moment, updated_at=moment)

        assert context.updated_at == context.created_at

    def test_rejects_non_mappingproxytype_metadata(self) -> None:
        with pytest.raises(TypeError):
            _make_context(metadata={"key": "value"})  # type: ignore[arg-type]

    def test_metadata_is_immutable(self) -> None:
        context = _make_context(
            metadata=MappingProxyType({"key": "value"})
        )

        with pytest.raises(TypeError):
            context.metadata["key"] = "other"  # type: ignore[index]

    def test_metadata_is_defensively_copied(self) -> None:
        source = {"key": "value"}

        context = _make_context(metadata=MappingProxyType(source))

        source["key"] = "changed"
        source["new"] = "added"

        assert dict(context.metadata) == {"key": "value"}

    def test_context_is_frozen(self) -> None:
        context = _make_context()

        with pytest.raises(AttributeError):
            context.context_id = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------
# register()
# ---------------------------------------------------------------------


class TestRegister:
    def test_register_stores_context(
        self,
        context_manager: ContextManager,
    ) -> None:
        context = _make_context(context_id="ctx-1")

        context_manager.register(context)

        assert context_manager.contains("ctx-1")
        assert context_manager.get("ctx-1") is context

    def test_register_publishes_registered_event(
        self,
        context_manager: ContextManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("context.registered", subscriber)

        context = _make_context(context_id="ctx-1")
        context_manager.register(context)

        assert len(subscriber.received) == 1
        event = subscriber.received[0]
        assert isinstance(event, ContextRegistered)
        assert event.context_id == "ctx-1"

    def test_register_rejects_duplicate_id(
        self,
        context_manager: ContextManager,
    ) -> None:
        context_manager.register(_make_context(context_id="ctx-1"))

        with pytest.raises(ContextAlreadyExistsError):
            context_manager.register(_make_context(context_id="ctx-1"))

    def test_register_rejects_invalid_type(
        self,
        context_manager: ContextManager,
    ) -> None:
        with pytest.raises(InvalidContextError):
            context_manager.register("not-a-context")  # type: ignore[arg-type]

    def test_duplicate_registration_does_not_publish_extra_event(
        self,
        context_manager: ContextManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("context.registered", subscriber)

        context_manager.register(_make_context(context_id="ctx-1"))

        with pytest.raises(ContextAlreadyExistsError):
            context_manager.register(_make_context(context_id="ctx-1"))

        assert len(subscriber.received) == 1


# ---------------------------------------------------------------------
# get() / contains()
# ---------------------------------------------------------------------


class TestGet:
    def test_get_returns_registered_context(
        self,
        context_manager: ContextManager,
    ) -> None:
        context = _make_context(context_id="ctx-1")
        context_manager.register(context)

        assert context_manager.get("ctx-1") is context

    def test_get_raises_when_missing(
        self,
        context_manager: ContextManager,
    ) -> None:
        with pytest.raises(ContextNotFoundError):
            context_manager.get("missing")


class TestContains:
    def test_contains_true_when_registered(
        self,
        context_manager: ContextManager,
    ) -> None:
        context_manager.register(_make_context(context_id="ctx-1"))

        assert context_manager.contains("ctx-1") is True

    def test_contains_false_when_missing(
        self,
        context_manager: ContextManager,
    ) -> None:
        assert context_manager.contains("missing") is False


# ---------------------------------------------------------------------
# update() (replace)
# ---------------------------------------------------------------------


class TestUpdate:
    def test_update_replaces_stored_context(
        self,
        context_manager: ContextManager,
    ) -> None:
        original = _make_context(
            context_id="ctx-1",
            status=ContextStatus.ACTIVE,
        )
        context_manager.register(original)

        replacement = _make_context(
            context_id="ctx-1",
            status=ContextStatus.COMPLETED,
        )
        context_manager.update(replacement)

        stored = context_manager.get("ctx-1")
        assert stored is replacement
        assert stored is not original
        assert stored.status is ContextStatus.COMPLETED

    def test_update_publishes_updated_event(
        self,
        context_manager: ContextManager,
        event_bus: EventBus,
    ) -> None:
        context_manager.register(_make_context(context_id="ctx-1"))

        subscriber = RecordingSubscriber()
        event_bus.subscribe("context.updated", subscriber)

        context_manager.update(
            _make_context(context_id="ctx-1", status=ContextStatus.FAILED)
        )

        assert len(subscriber.received) == 1
        event = subscriber.received[0]
        assert isinstance(event, ContextUpdated)
        assert event.context_id == "ctx-1"

    def test_update_raises_when_missing(
        self,
        context_manager: ContextManager,
    ) -> None:
        with pytest.raises(ContextNotFoundError):
            context_manager.update(_make_context(context_id="missing"))

    def test_update_rejects_invalid_type(
        self,
        context_manager: ContextManager,
    ) -> None:
        with pytest.raises(InvalidContextError):
            context_manager.update("not-a-context")  # type: ignore[arg-type]

    def test_update_missing_does_not_publish_event(
        self,
        context_manager: ContextManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("context.updated", subscriber)

        with pytest.raises(ContextNotFoundError):
            context_manager.update(_make_context(context_id="missing"))

        assert len(subscriber.received) == 0


# ---------------------------------------------------------------------
# remove()
# ---------------------------------------------------------------------


class TestRemove:
    def test_remove_deletes_context(
        self,
        context_manager: ContextManager,
    ) -> None:
        context_manager.register(_make_context(context_id="ctx-1"))

        context_manager.remove("ctx-1")

        assert not context_manager.contains("ctx-1")

    def test_remove_publishes_removed_event(
        self,
        context_manager: ContextManager,
        event_bus: EventBus,
    ) -> None:
        context_manager.register(_make_context(context_id="ctx-1"))

        subscriber = RecordingSubscriber()
        event_bus.subscribe("context.removed", subscriber)

        context_manager.remove("ctx-1")

        assert len(subscriber.received) == 1
        event = subscriber.received[0]
        assert isinstance(event, ContextRemoved)
        assert event.context_id == "ctx-1"

    def test_remove_raises_when_missing(
        self,
        context_manager: ContextManager,
    ) -> None:
        with pytest.raises(ContextNotFoundError):
            context_manager.remove("missing")

    def test_remove_missing_does_not_publish_event(
        self,
        context_manager: ContextManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("context.removed", subscriber)

        with pytest.raises(ContextNotFoundError):
            context_manager.remove("missing")

        assert len(subscriber.received) == 0


# ---------------------------------------------------------------------
# get_all() / count()
# ---------------------------------------------------------------------


class TestGetAllAndCount:
    def test_get_all_returns_every_registered_context(
        self,
        context_manager: ContextManager,
    ) -> None:
        context_a = _make_context(context_id="a")
        context_b = _make_context(context_id="b")
        context_manager.register(context_a)
        context_manager.register(context_b)

        results = context_manager.get_all()
        assert len(results) == 2
        assert context_a in results
        assert context_b in results

    def test_get_all_returns_empty_tuple_when_none_registered(
        self,
        context_manager: ContextManager,
    ) -> None:
        assert context_manager.get_all() == ()

    def test_get_all_is_a_point_in_time_snapshot(
        self,
        context_manager: ContextManager,
    ) -> None:
        context_manager.register(_make_context(context_id="a"))

        snapshot = context_manager.get_all()

        context_manager.register(_make_context(context_id="b"))

        assert len(snapshot) == 1
        assert len(context_manager.get_all()) == 2

    def test_count_reflects_registry_size(
        self,
        context_manager: ContextManager,
    ) -> None:
        assert context_manager.count() == 0

        context_manager.register(_make_context(context_id="a"))
        assert context_manager.count() == 1

        context_manager.register(_make_context(context_id="b"))
        assert context_manager.count() == 2

        context_manager.remove("a")
        assert context_manager.count() == 1


# ---------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_registration_of_distinct_ids_succeeds(
        self,
        context_manager: ContextManager,
    ) -> None:
        context_ids = [f"ctx-{i}" for i in range(50)]
        errors: list[Exception] = []

        def _register(context_id: str) -> None:
            try:
                context_manager.register(_make_context(context_id=context_id))
            except Exception as ex:  # pragma: no cover - failure path
                errors.append(ex)

        threads = [
            threading.Thread(target=_register, args=(context_id,))
            for context_id in context_ids
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        assert errors == []
        assert context_manager.count() == len(context_ids)
        assert all(
            context_manager.contains(context_id) for context_id in context_ids
        )
