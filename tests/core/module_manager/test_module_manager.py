"""
Unit tests for ModuleManager.

ModuleManager is exercised in isolation using a local fake
``ModuleDriver`` implementation, so these tests do not depend on any
real PARIKA Module. Real ``Configuration``, ``EventBus``, and
``Logger`` instances are used (via the shared fixtures in
``tests/conftest.py``) since ModuleManager's constructor does not
strictly type-check its dependencies but the rest of the suite's
convention is to use real Core services rather than fakes.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.module_manager.driver import ModuleDriver
from parika.core.module_manager.events import (
    ModuleLoadedEvent,
    ModuleRegisteredEvent,
    ModuleStateChangedEvent,
    ModuleUnloadedEvent,
    ModuleUnregisteredEvent,
)
from parika.core.module_manager.exceptions import (
    ModuleAlreadyLoadedError,
    ModuleAlreadyRegisteredError,
    ModuleLoadError,
    ModuleNotFoundError,
    ModuleNotLoadedError,
    ModuleUnloadError,
)
from parika.core.module_manager.manifest import ModuleManifest
from parika.core.module_manager.module import Module
from parika.core.module_manager.module_manager import ModuleManager
from parika.core.module_manager.state import ModuleState


class RecordingSubscriber:
    def __init__(self) -> None:
        self.received: list[Any] = []

    def __call__(self, payload: Any) -> None:
        self.received.append(payload)


class FakeModuleDriver(ModuleDriver):
    """
    Minimal ``ModuleDriver`` used to test ``ModuleManager`` in
    isolation, with call tracking and optional failure injection so
    both the success and failure paths of ``load()``/``unload()`` can
    be exercised without depending on any real Module driver.
    """

    def __init__(
        self,
        *,
        fail_on_start: bool = False,
        fail_on_stop: bool = False,
    ) -> None:
        self.start_calls = 0
        self.stop_calls = 0
        self._fail_on_start = fail_on_start
        self._fail_on_stop = fail_on_stop

    def start(self) -> None:
        self.start_calls += 1

        if self._fail_on_start:
            raise RuntimeError("start failed")

    def stop(self) -> None:
        self.stop_calls += 1

        if self._fail_on_stop:
            raise RuntimeError("stop failed")


def _make_manifest(module_id: str = "test_module") -> ModuleManifest:
    return ModuleManifest(
        id=module_id,
        name="Test Module",
        version="1.0.0",
        description="A module used for ModuleManager unit tests.",
        author="PARIKA",
        license="MIT",
        driver=(
            "tests.core.module_manager.test_module_manager."
            "FakeModuleDriver"
        ),
    )


def _make_module(
    module_id: str = "test_module",
    *,
    driver: ModuleDriver | None = None,
    state: ModuleState = ModuleState.INACTIVE,
) -> Module:
    return Module(
        id=module_id,
        manifest=_make_manifest(module_id),
        driver=driver if driver is not None else FakeModuleDriver(),
        state=state,
    )


@pytest.fixture
def module_manager(
    configuration: Configuration,
    event_bus: EventBus,
    logger: Logger,
) -> ModuleManager:
    return ModuleManager(
        configuration=configuration,
        event_bus=event_bus,
        logger=logger,
    )


# ---------------------------------------------------------------------
# register()
# ---------------------------------------------------------------------


class TestRegister:
    def test_register_success(
        self,
        module_manager: ModuleManager,
    ) -> None:
        module = _make_module()

        module_manager.register(module)

        assert module_manager.contains("test_module")
        registered = module_manager.get("test_module")
        assert registered is module

    def test_register_preserves_caller_supplied_state(
        self,
        module_manager: ModuleManager,
    ) -> None:
        """
        ``ModuleManager.register()`` does not assign or normalize a
        module's initial state itself; the ``Module`` passed in
        already carries whatever ``ModuleState`` its creator chose
        (conventionally ``INACTIVE``), and registration stores it
        verbatim.
        """
        module = _make_module(state=ModuleState.INACTIVE)

        module_manager.register(module)

        assert module_manager.get("test_module").state is (
            ModuleState.INACTIVE
        )

    def test_register_duplicate_id_raises(
        self,
        module_manager: ModuleManager,
    ) -> None:
        module_manager.register(_make_module())

        with pytest.raises(ModuleAlreadyRegisteredError):
            module_manager.register(_make_module())

    def test_register_duplicate_does_not_replace_existing(
        self,
        module_manager: ModuleManager,
    ) -> None:
        original = _make_module()
        module_manager.register(original)

        with pytest.raises(ModuleAlreadyRegisteredError):
            module_manager.register(_make_module())

        assert module_manager.get("test_module") is original

    def test_register_publishes_registered_event(
        self,
        module_manager: ModuleManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("module.registered", subscriber)

        module = _make_module()
        module_manager.register(module)

        assert len(subscriber.received) == 1
        event = subscriber.received[0]
        assert isinstance(event, ModuleRegisteredEvent)
        assert event.module is module

    def test_register_does_not_validate_argument_type(
        self,
        module_manager: ModuleManager,
    ) -> None:
        """
        ``register()`` performs no ``isinstance`` check against
        ``Module``; it only requires the argument to expose an ``id``
        attribute (duck typing via ``module.id in self._modules``).
        There is no ModuleManager-specific "invalid type" exception:
        an object lacking an ``id`` attribute fails with a plain
        ``AttributeError`` instead.
        """

        class _NotAModule:
            pass

        with pytest.raises(AttributeError):
            module_manager.register(_NotAModule())  # type: ignore[arg-type]


# ---------------------------------------------------------------------
# unregister()
# ---------------------------------------------------------------------


class TestUnregister:
    def test_unregister_success(
        self,
        module_manager: ModuleManager,
    ) -> None:
        module_manager.register(_make_module())

        module_manager.unregister("test_module")

        assert not module_manager.contains("test_module")

    def test_unregister_not_found_raises(
        self,
        module_manager: ModuleManager,
    ) -> None:
        with pytest.raises(ModuleNotFoundError):
            module_manager.unregister("missing")

    def test_unregister_publishes_unregistered_event(
        self,
        module_manager: ModuleManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("module.unregistered", subscriber)

        module = _make_module()
        module_manager.register(module)
        module_manager.unregister("test_module")

        assert len(subscriber.received) == 1
        event = subscriber.received[0]
        assert isinstance(event, ModuleUnregisteredEvent)
        assert event.module is module

    def test_unregister_allows_removing_an_active_module(
        self,
        module_manager: ModuleManager,
    ) -> None:
        """
        BUG FOUND: parika/core/module_manager/module_manager.py:96-113
        (``unregister()``).

        Unlike ``unload()``, ``unregister()`` performs no check on the
        module's current ``ModuleState`` and never calls
        ``module.driver.stop()``. This means an ``ACTIVE`` module can
        be unregistered directly (bypassing ``unload()``), silently
        leaving its driver's acquired resources (whatever ``start()``
        set up) running with no reference left in the registry and no
        ``module.unloaded``/``module.state_changed`` event published.

        This test documents the current actual behavior (unregister
        succeeds unconditionally) rather than fixing it, per the
        frozen-architecture constraint.
        """
        driver = FakeModuleDriver()
        module_manager.register(_make_module(driver=driver))
        module_manager.load("test_module")
        assert module_manager.get("test_module").state is (
            ModuleState.ACTIVE
        )

        module_manager.unregister("test_module")

        assert not module_manager.contains("test_module")
        # driver.stop() was never invoked despite the module having
        # been ACTIVE.
        assert driver.stop_calls == 0


# ---------------------------------------------------------------------
# get() / contains() / get_all() / get_active()
# ---------------------------------------------------------------------


class TestLookup:
    def test_get_returns_registered_module(
        self,
        module_manager: ModuleManager,
    ) -> None:
        module = _make_module()
        module_manager.register(module)

        assert module_manager.get("test_module") is module

    def test_get_not_found_raises(
        self,
        module_manager: ModuleManager,
    ) -> None:
        with pytest.raises(ModuleNotFoundError):
            module_manager.get("missing")

    def test_contains_true_for_registered_module(
        self,
        module_manager: ModuleManager,
    ) -> None:
        module_manager.register(_make_module())

        assert module_manager.contains("test_module") is True

    def test_contains_false_for_unregistered_module(
        self,
        module_manager: ModuleManager,
    ) -> None:
        assert module_manager.contains("missing") is False

    def test_get_all_returns_every_registered_module(
        self,
        module_manager: ModuleManager,
    ) -> None:
        """
        Note: ``Module``/``ModuleManifest`` are frozen dataclasses but
        are NOT hashable in practice (``ModuleManifest.metadata``
        defaults to a mutable ``dict``, so ``hash()`` raises
        ``TypeError`` at call time despite the class defining
        ``__hash__``). Comparisons here use ids/identity rather than
        ``set()`` membership for that reason.
        """
        first = _make_module("first")
        second = _make_module("second")
        module_manager.register(first)
        module_manager.register(second)

        all_modules = module_manager.get_all()

        assert isinstance(all_modules, tuple)
        assert {module.id for module in all_modules} == {"first", "second"}
        assert first in all_modules
        assert second in all_modules

    def test_get_all_empty_when_nothing_registered(
        self,
        module_manager: ModuleManager,
    ) -> None:
        assert module_manager.get_all() == ()

    def test_get_active_returns_only_active_modules(
        self,
        module_manager: ModuleManager,
    ) -> None:
        active = _make_module("active_module")
        inactive = _make_module("inactive_module")
        module_manager.register(active)
        module_manager.register(inactive)

        module_manager.load("active_module")

        active_modules = module_manager.get_active()

        assert isinstance(active_modules, tuple)
        assert len(active_modules) == 1
        assert active_modules[0].id == "active_module"
        assert active_modules[0].state is ModuleState.ACTIVE

    def test_get_active_empty_when_none_active(
        self,
        module_manager: ModuleManager,
    ) -> None:
        module_manager.register(_make_module())

        assert module_manager.get_active() == ()

    def test_no_count_method_exists(
        self,
        module_manager: ModuleManager,
    ) -> None:
        """
        Documents that ``ModuleManager`` has no dedicated ``count()``
        method; enumeration count must be derived from
        ``len(get_all())`` instead.
        """
        assert not hasattr(module_manager, "count")

        module_manager.register(_make_module("a"))
        module_manager.register(_make_module("b"))

        assert len(module_manager.get_all()) == 2


# ---------------------------------------------------------------------
# load()
# ---------------------------------------------------------------------


class TestLoad:
    def test_load_success_starts_driver_and_activates_module(
        self,
        module_manager: ModuleManager,
    ) -> None:
        driver = FakeModuleDriver()
        module_manager.register(_make_module(driver=driver))

        module_manager.load("test_module")

        assert driver.start_calls == 1
        assert module_manager.get("test_module").state is (
            ModuleState.ACTIVE
        )

    def test_load_not_found_raises(
        self,
        module_manager: ModuleManager,
    ) -> None:
        with pytest.raises(ModuleNotFoundError):
            module_manager.load("missing")

    def test_load_already_active_raises_without_restarting_driver(
        self,
        module_manager: ModuleManager,
    ) -> None:
        driver = FakeModuleDriver()
        module_manager.register(_make_module(driver=driver))
        module_manager.load("test_module")

        with pytest.raises(ModuleAlreadyLoadedError):
            module_manager.load("test_module")

        assert driver.start_calls == 1

    def test_load_publishes_loaded_and_state_changed_events(
        self,
        module_manager: ModuleManager,
        event_bus: EventBus,
    ) -> None:
        loaded_subscriber = RecordingSubscriber()
        state_changed_subscriber = RecordingSubscriber()
        event_bus.subscribe("module.loaded", loaded_subscriber)
        event_bus.subscribe(
            "module.state_changed", state_changed_subscriber
        )

        module_manager.register(_make_module())
        module_manager.load("test_module")

        assert len(loaded_subscriber.received) == 1
        loaded_event = loaded_subscriber.received[0]
        assert isinstance(loaded_event, ModuleLoadedEvent)
        assert loaded_event.module.state is ModuleState.ACTIVE

        assert len(state_changed_subscriber.received) == 1
        state_event = state_changed_subscriber.received[0]
        assert isinstance(state_event, ModuleStateChangedEvent)
        assert state_event.previous_state is ModuleState.INACTIVE
        assert state_event.current_state is ModuleState.ACTIVE

    def test_load_failure_transitions_to_failed_and_wraps_exception(
        self,
        module_manager: ModuleManager,
    ) -> None:
        driver = FakeModuleDriver(fail_on_start=True)
        module_manager.register(_make_module(driver=driver))

        with pytest.raises(ModuleLoadError) as excinfo:
            module_manager.load("test_module")

        assert isinstance(excinfo.value.__cause__, RuntimeError)
        assert str(excinfo.value.__cause__) == "start failed"
        assert module_manager.get("test_module").state is (
            ModuleState.FAILED
        )

    def test_load_failure_publishes_only_state_changed_event(
        self,
        module_manager: ModuleManager,
        event_bus: EventBus,
    ) -> None:
        """
        There is no dedicated "module.load_failed" event; on failure
        only ``module.state_changed`` (to ``FAILED``) is published,
        while ``module.loaded`` is never published for a failed load.
        """
        loaded_subscriber = RecordingSubscriber()
        state_changed_subscriber = RecordingSubscriber()
        event_bus.subscribe("module.loaded", loaded_subscriber)
        event_bus.subscribe(
            "module.state_changed", state_changed_subscriber
        )

        driver = FakeModuleDriver(fail_on_start=True)
        module_manager.register(_make_module(driver=driver))

        with pytest.raises(ModuleLoadError):
            module_manager.load("test_module")

        assert len(loaded_subscriber.received) == 0
        assert len(state_changed_subscriber.received) == 1
        state_event = state_changed_subscriber.received[0]
        assert state_event.previous_state is ModuleState.INACTIVE
        assert state_event.current_state is ModuleState.FAILED


# ---------------------------------------------------------------------
# unload()
# ---------------------------------------------------------------------


class TestUnload:
    def test_unload_success_stops_driver_and_deactivates_module(
        self,
        module_manager: ModuleManager,
    ) -> None:
        driver = FakeModuleDriver()
        module_manager.register(_make_module(driver=driver))
        module_manager.load("test_module")

        module_manager.unload("test_module")

        assert driver.stop_calls == 1
        assert module_manager.get("test_module").state is (
            ModuleState.INACTIVE
        )

    def test_unload_not_found_raises(
        self,
        module_manager: ModuleManager,
    ) -> None:
        with pytest.raises(ModuleNotFoundError):
            module_manager.unload("missing")

    def test_unload_not_currently_loaded_raises(
        self,
        module_manager: ModuleManager,
    ) -> None:
        driver = FakeModuleDriver()
        module_manager.register(_make_module(driver=driver))

        with pytest.raises(ModuleNotLoadedError):
            module_manager.unload("test_module")

        assert driver.stop_calls == 0

    def test_unload_publishes_unloaded_and_state_changed_events(
        self,
        module_manager: ModuleManager,
        event_bus: EventBus,
    ) -> None:
        unloaded_subscriber = RecordingSubscriber()
        state_changed_subscriber = RecordingSubscriber()
        event_bus.subscribe("module.unloaded", unloaded_subscriber)
        event_bus.subscribe(
            "module.state_changed", state_changed_subscriber
        )

        module_manager.register(_make_module())
        module_manager.load("test_module")
        # Only inspect events published by unload(); ignore the pair
        # published by load() above.
        state_changed_subscriber.received.clear()

        module_manager.unload("test_module")

        assert len(unloaded_subscriber.received) == 1
        unloaded_event = unloaded_subscriber.received[0]
        assert isinstance(unloaded_event, ModuleUnloadedEvent)
        assert unloaded_event.module.state is ModuleState.INACTIVE

        assert len(state_changed_subscriber.received) == 1
        state_event = state_changed_subscriber.received[0]
        assert isinstance(state_event, ModuleStateChangedEvent)
        assert state_event.previous_state is ModuleState.ACTIVE
        assert state_event.current_state is ModuleState.INACTIVE

    def test_unload_failure_propagates_and_transitions_to_failed(
        self,
        module_manager: ModuleManager,
    ) -> None:
        """
        Unlike LifecycleManager's shutdown hooks (which are
        best-effort and continue running remaining hooks despite a
        failure), ``ModuleManager.unload()`` propagates the driver's
        ``stop()`` exception (wrapped in ``ModuleUnloadError``) rather
        than swallowing it, and transitions the module to ``FAILED``
        instead of leaving it or reverting it to ``INACTIVE``.
        """
        driver = FakeModuleDriver(fail_on_stop=True)
        module_manager.register(_make_module(driver=driver))
        module_manager.load("test_module")

        with pytest.raises(ModuleUnloadError) as excinfo:
            module_manager.unload("test_module")

        assert isinstance(excinfo.value.__cause__, RuntimeError)
        assert str(excinfo.value.__cause__) == "stop failed"
        assert module_manager.get("test_module").state is (
            ModuleState.FAILED
        )

    def test_unload_failure_publishes_only_state_changed_event(
        self,
        module_manager: ModuleManager,
        event_bus: EventBus,
    ) -> None:
        unloaded_subscriber = RecordingSubscriber()
        state_changed_subscriber = RecordingSubscriber()
        event_bus.subscribe("module.unloaded", unloaded_subscriber)
        event_bus.subscribe(
            "module.state_changed", state_changed_subscriber
        )

        driver = FakeModuleDriver(fail_on_stop=True)
        module_manager.register(_make_module(driver=driver))
        module_manager.load("test_module")
        state_changed_subscriber.received.clear()

        with pytest.raises(ModuleUnloadError):
            module_manager.unload("test_module")

        assert len(unloaded_subscriber.received) == 0
        assert len(state_changed_subscriber.received) == 1
        state_event = state_changed_subscriber.received[0]
        assert state_event.previous_state is ModuleState.ACTIVE
        assert state_event.current_state is ModuleState.FAILED


# ---------------------------------------------------------------------
# load_all() / unload_all()
# ---------------------------------------------------------------------


class TestLoadAllUnloadAll:
    def test_load_all_starts_every_non_active_module(
        self,
        module_manager: ModuleManager,
    ) -> None:
        first_driver = FakeModuleDriver()
        second_driver = FakeModuleDriver()
        module_manager.register(_make_module("first", driver=first_driver))
        module_manager.register(
            _make_module("second", driver=second_driver)
        )

        module_manager.load_all()

        assert first_driver.start_calls == 1
        assert second_driver.start_calls == 1
        assert len(module_manager.get_active()) == 2

    def test_unload_all_stops_every_active_module(
        self,
        module_manager: ModuleManager,
    ) -> None:
        first_driver = FakeModuleDriver()
        second_driver = FakeModuleDriver()
        module_manager.register(_make_module("first", driver=first_driver))
        module_manager.register(
            _make_module("second", driver=second_driver)
        )
        module_manager.load_all()

        module_manager.unload_all()

        assert first_driver.stop_calls == 1
        assert second_driver.stop_calls == 1
        assert module_manager.get_active() == ()


# ---------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_register_calls_for_distinct_ids(
        self,
        module_manager: ModuleManager,
    ) -> None:
        """
        ``ModuleManager`` guards its internal registry with an
        ``RLock``. Registering distinct module ids concurrently from
        multiple threads must not lose or corrupt any registration.
        """
        thread_count = 20
        errors: list[BaseException] = []

        def _register(index: int) -> None:
            try:
                module_manager.register(_make_module(f"module-{index}"))
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
        assert len(module_manager.get_all()) == thread_count
        for i in range(thread_count):
            assert module_manager.contains(f"module-{i}")
