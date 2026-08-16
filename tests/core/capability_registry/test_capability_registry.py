"""
Unit tests for CapabilityRegistry.

CapabilityRegistry is exercised directly against real EventBus and
Logger instances (via the shared `logger`/`event_bus` fixtures) since
it holds no dependencies that require test doubles.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from parika.core.capability_registry.capability_category import (
    CapabilityCategory,
)
from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)
from parika.core.capability_registry.capability_registry import (
    CapabilityRegistry,
)
from parika.core.capability_registry.events import (
    CapabilityDisabled,
    CapabilityEnabled,
    CapabilityRegistered,
    CapabilityUnregistered,
)
from parika.core.capability_registry.exceptions import (
    CapabilityAlreadyRegisteredError,
    CapabilityNotFoundError,
    InvalidCapabilityError,
)
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger


class RecordingSubscriber:
    """EventBus subscriber that records every payload it receives."""

    def __init__(self) -> None:
        self.received: list[Any] = []

    def __call__(self, payload: Any) -> None:
        self.received.append(payload)


@pytest.fixture
def capability_registry(
    event_bus: EventBus,
    logger: Logger,
) -> CapabilityRegistry:
    return CapabilityRegistry(event_bus=event_bus, logger=logger)


def _make_definition(
    *,
    id: str = "web.search",
    name: str = "Web Search",
    description: str = "Search the web.",
    category: CapabilityCategory = CapabilityCategory.TOOL,
    tags: frozenset[str] = frozenset(),
    enabled: bool = True,
) -> CapabilityDefinition:
    return CapabilityDefinition(
        id=id,
        name=name,
        description=description,
        category=category,
        tags=tags,
        enabled=enabled,
    )


# ---------------------------------------------------------------------
# register()
# ---------------------------------------------------------------------


class TestRegister:
    def test_registers_capability(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        definition = _make_definition()

        capability_registry.register(definition)

        assert capability_registry.contains("web.search")
        assert capability_registry.get("web.search") is definition

    def test_publishes_registered_event(
        self,
        capability_registry: CapabilityRegistry,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("capability.registered", subscriber)

        definition = _make_definition()
        capability_registry.register(definition)

        assert len(subscriber.received) == 1
        event = subscriber.received[0]
        assert isinstance(event, CapabilityRegistered)
        assert event.capability_id == "web.search"

    def test_rejects_duplicate_registration(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        capability_registry.register(_make_definition())

        with pytest.raises(CapabilityAlreadyRegisteredError):
            capability_registry.register(_make_definition())

    def test_rejects_empty_id(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        with pytest.raises(InvalidCapabilityError):
            capability_registry.register(_make_definition(id="   "))

    def test_rejects_empty_name(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        with pytest.raises(InvalidCapabilityError):
            capability_registry.register(_make_definition(name=""))

    def test_rejects_invalid_category_type(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        # CapabilityDefinition itself performs no runtime type
        # validation of `category` (it is a plain dataclass field), so
        # a definition with a non-CapabilityCategory category can be
        # constructed directly. CapabilityRegistry.register() is
        # responsible for rejecting it.
        bad_definition = CapabilityDefinition(
            id="bad.capability",
            name="Bad",
            description="Bad category.",
            category="not-a-category",  # type: ignore[arg-type]
        )

        with pytest.raises(InvalidCapabilityError):
            capability_registry.register(bad_definition)

    def test_indexes_by_category(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        definition = _make_definition(category=CapabilityCategory.LLM)
        capability_registry.register(definition)

        results = capability_registry.get_by_category(CapabilityCategory.LLM)

        assert results == (definition,)

    def test_indexes_by_tags(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        definition = _make_definition(tags=frozenset({"search", "web"}))
        capability_registry.register(definition)

        assert capability_registry.get_by_tag("search") == (definition,)
        assert capability_registry.get_by_tag("web") == (definition,)


# ---------------------------------------------------------------------
# unregister()
# ---------------------------------------------------------------------


class TestUnregister:
    def test_removes_capability(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        capability_registry.register(_make_definition())

        capability_registry.unregister("web.search")

        assert not capability_registry.contains("web.search")

    def test_publishes_unregistered_event(
        self,
        capability_registry: CapabilityRegistry,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("capability.unregistered", subscriber)

        capability_registry.register(_make_definition())
        capability_registry.unregister("web.search")

        assert len(subscriber.received) == 1
        event = subscriber.received[0]
        assert isinstance(event, CapabilityUnregistered)
        assert event.capability_id == "web.search"

    def test_raises_when_missing(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        with pytest.raises(CapabilityNotFoundError):
            capability_registry.unregister("missing.capability")

    def test_cleans_up_category_index(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        capability_registry.register(
            _make_definition(category=CapabilityCategory.LLM)
        )

        capability_registry.unregister("web.search")

        assert capability_registry.get_by_category(CapabilityCategory.LLM) == ()

    def test_cleans_up_tag_index(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        capability_registry.register(
            _make_definition(tags=frozenset({"search"}))
        )

        capability_registry.unregister("web.search")

        assert capability_registry.get_by_tag("search") == ()

    def test_removing_one_capability_preserves_shared_tag_for_others(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        first = _make_definition(id="web.search", tags=frozenset({"shared"}))
        second = _make_definition(id="web.crawl", tags=frozenset({"shared"}))
        capability_registry.register(first)
        capability_registry.register(second)

        capability_registry.unregister("web.search")

        assert capability_registry.get_by_tag("shared") == (second,)


# ---------------------------------------------------------------------
# contains() / get() / get_all()
# ---------------------------------------------------------------------


class TestRegistryLookup:
    def test_contains_reflects_registry_state(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        assert not capability_registry.contains("web.search")

        capability_registry.register(_make_definition())

        assert capability_registry.contains("web.search")

    def test_get_raises_when_missing(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        with pytest.raises(CapabilityNotFoundError):
            capability_registry.get("missing.capability")

    def test_get_all_returns_all_registered_definitions(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        first = _make_definition(id="a")
        second = _make_definition(id="b")
        capability_registry.register(first)
        capability_registry.register(second)

        # CapabilityDefinition is unhashable (its default metadata
        # field is a MappingProxyType), so results are compared as
        # id sets rather than placed into a set themselves.
        result_ids = {definition.id for definition in capability_registry.get_all()}
        assert result_ids == {"a", "b"}

    def test_get_all_returns_empty_tuple_when_empty(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        assert capability_registry.get_all() == ()


# ---------------------------------------------------------------------
# find()
# ---------------------------------------------------------------------


class TestFind:
    def test_find_without_filters_returns_all(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        first = _make_definition(id="a")
        second = _make_definition(id="b")
        capability_registry.register(first)
        capability_registry.register(second)

        result_ids = {definition.id for definition in capability_registry.find()}
        assert result_ids == {"a", "b"}

    def test_find_by_category(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        tool = _make_definition(id="a", category=CapabilityCategory.TOOL)
        llm = _make_definition(id="b", category=CapabilityCategory.LLM)
        capability_registry.register(tool)
        capability_registry.register(llm)

        assert capability_registry.find(category=CapabilityCategory.LLM) == (
            llm,
        )

    def test_find_by_tag(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        tagged = _make_definition(id="a", tags=frozenset({"search"}))
        untagged = _make_definition(id="b")
        capability_registry.register(tagged)
        capability_registry.register(untagged)

        assert capability_registry.find(tag="search") == (tagged,)

    def test_find_by_enabled_state(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        enabled = _make_definition(id="a", enabled=True)
        disabled = _make_definition(id="b", enabled=False)
        capability_registry.register(enabled)
        capability_registry.register(disabled)

        assert capability_registry.find(enabled=True) == (enabled,)
        assert capability_registry.find(enabled=False) == (disabled,)

    def test_find_combines_category_and_tag_filters(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        matching = _make_definition(
            id="a",
            category=CapabilityCategory.TOOL,
            tags=frozenset({"search"}),
        )
        wrong_tag = _make_definition(
            id="b",
            category=CapabilityCategory.TOOL,
            tags=frozenset({"other"}),
        )
        wrong_category = _make_definition(
            id="c",
            category=CapabilityCategory.LLM,
            tags=frozenset({"search"}),
        )
        capability_registry.register(matching)
        capability_registry.register(wrong_tag)
        capability_registry.register(wrong_category)

        result = capability_registry.find(
            category=CapabilityCategory.TOOL,
            tag="search",
        )

        assert result == (matching,)

    def test_find_returns_empty_when_no_match(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        capability_registry.register(_make_definition())

        assert capability_registry.find(category=CapabilityCategory.MEMORY) == ()


# ---------------------------------------------------------------------
# enable() / disable()
# ---------------------------------------------------------------------


class TestEnableDisable:
    def test_disable_marks_capability_disabled(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        capability_registry.register(_make_definition(enabled=True))

        capability_registry.disable("web.search")

        assert capability_registry.get("web.search").enabled is False

    def test_disable_publishes_event(
        self,
        capability_registry: CapabilityRegistry,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("capability.disabled", subscriber)

        capability_registry.register(_make_definition(enabled=True))
        capability_registry.disable("web.search")

        assert len(subscriber.received) == 1
        assert isinstance(subscriber.received[0], CapabilityDisabled)
        assert subscriber.received[0].capability_id == "web.search"

    def test_disable_is_idempotent_and_does_not_republish(
        self,
        capability_registry: CapabilityRegistry,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("capability.disabled", subscriber)

        capability_registry.register(_make_definition(enabled=False))
        capability_registry.disable("web.search")

        assert len(subscriber.received) == 0

    def test_disable_raises_when_missing(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        with pytest.raises(CapabilityNotFoundError):
            capability_registry.disable("missing.capability")

    def test_enable_marks_capability_enabled(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        capability_registry.register(_make_definition(enabled=False))

        capability_registry.enable("web.search")

        assert capability_registry.get("web.search").enabled is True

    def test_enable_publishes_event(
        self,
        capability_registry: CapabilityRegistry,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("capability.enabled", subscriber)

        capability_registry.register(_make_definition(enabled=False))
        capability_registry.enable("web.search")

        assert len(subscriber.received) == 1
        assert isinstance(subscriber.received[0], CapabilityEnabled)
        assert subscriber.received[0].capability_id == "web.search"

    def test_enable_is_idempotent_and_does_not_republish(
        self,
        capability_registry: CapabilityRegistry,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("capability.enabled", subscriber)

        capability_registry.register(_make_definition(enabled=True))
        capability_registry.enable("web.search")

        assert len(subscriber.received) == 0

    def test_enable_raises_when_missing(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        with pytest.raises(CapabilityNotFoundError):
            capability_registry.enable("missing.capability")

    def test_enable_replaces_definition_without_mutating_original(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        original = _make_definition(enabled=False)
        capability_registry.register(original)

        capability_registry.enable("web.search")

        assert original.enabled is False
        assert capability_registry.get("web.search").enabled is True
        assert capability_registry.get("web.search") is not original


# ---------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------


class TestImmutability:
    def test_definition_is_frozen(self) -> None:
        definition = _make_definition()

        with pytest.raises(AttributeError):
            definition.enabled = False  # type: ignore[misc]

    def test_get_all_is_a_tuple(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        capability_registry.register(_make_definition())

        result = capability_registry.get_all()

        with pytest.raises(AttributeError):
            result.append(_make_definition(id="other"))  # type: ignore[attr-defined]


# ---------------------------------------------------------------------
# NOTE: metadata was previously not defensively copied into an
# immutable mapping on CapabilityDefinition, unlike sibling immutable
# value objects (Tool, ToolRequest, CapabilityExecutionRequest, ...)
# which all perform this conversion in __post_init__. This was fixed
# (capability_definition.py) to add the same __post_init__ freeze.
# ---------------------------------------------------------------------


class TestMetadataImmutabilityGap:
    def test_metadata_is_defensively_copied(self) -> None:
        mutable_metadata = {"trace_id": "abc"}

        definition = _make_definition()
        definition = CapabilityDefinition(
            id=definition.id,
            name=definition.name,
            description=definition.description,
            category=definition.category,
            metadata=mutable_metadata,  # type: ignore[arg-type]
        )

        # The definition holds its own immutable copy; mutating the
        # original dict afterward does not leak into the definition.
        assert definition.metadata == {"trace_id": "abc"}
        assert definition.metadata is not mutable_metadata

        mutable_metadata["trace_id"] = "mutated"
        assert definition.metadata["trace_id"] == "abc"

        with pytest.raises(TypeError):
            definition.metadata["trace_id"] = "mutated"  # type: ignore[index]


# ---------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------
#
# CapabilityRegistry guards its mutation operations (register,
# unregister, enable, disable) with an internal RLock, so concurrent
# writers should never corrupt the registry state.


class TestThreadSafety:
    def test_concurrent_registrations_do_not_corrupt_registry(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        thread_count = 16
        errors: list[BaseException] = []

        def _register(index: int) -> None:
            try:
                capability_registry.register(
                    _make_definition(
                        id=f"capability.{index}",
                        tags=frozenset({"shared"}),
                    )
                )
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [
            threading.Thread(target=_register, args=(i,))
            for i in range(thread_count)
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        assert errors == []
        assert len(capability_registry.get_all()) == thread_count
        assert len(capability_registry.get_by_tag("shared")) == thread_count

        for i in range(thread_count):
            assert capability_registry.contains(f"capability.{i}")
