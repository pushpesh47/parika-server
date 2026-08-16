"""
Unit tests for LifecycleManager.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from parika.core.event_bus.event_bus import EventBus
from parika.core.lifecycle_manager.events import (
    LifecycleInitializedEvent,
    LifecycleReloadedEvent,
    LifecycleReloadFailedEvent,
    LifecycleStartedEvent,
    LifecycleStartFailedEvent,
    LifecycleStoppedEvent,
)
from parika.core.lifecycle_manager.exceptions import (
    AlreadyInitializedError,
    HookAlreadyRegisteredError,
    InvalidLifecycleTransitionError,
    LifecycleHookError,
    NotInitializedError,
)
from parika.core.lifecycle_manager.lifecycle_manager import LifecycleManager
from parika.core.state_manager.state_manager import StateManager
from parika.core.state_manager.states import LifecycleState


class _FakeLogger:
    def get_logger(self, name: str) -> logging.Logger:
        return logging.getLogger(name)


class RecordingSubscriber:
    def __init__(self) -> None:
        self.received: list[Any] = []

    def __call__(self, payload: Any) -> None:
        self.received.append(payload)


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus(logger=_FakeLogger())  # type: ignore[arg-type]


@pytest.fixture
def state_manager() -> StateManager:
    return StateManager(logger=_FakeLogger())  # type: ignore[arg-type]


@pytest.fixture
def lifecycle_manager(
    state_manager: StateManager,
    event_bus: EventBus,
) -> LifecycleManager:
    return LifecycleManager(
        state_manager=state_manager,
        event_bus=event_bus,
        logger=_FakeLogger(),  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------
# Hook registration
# ---------------------------------------------------------------------


class TestHookRegistration:
    def test_registers_hooks_for_each_phase(
        self,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        lifecycle_manager.register_initialize_hook("a", lambda: None)
        lifecycle_manager.register_startup_hook("b", lambda: None)
        lifecycle_manager.register_shutdown_hook("c", lambda: None)
        lifecycle_manager.register_reload_hook("d", lambda: None)

    def test_rejects_duplicate_hook_names_within_same_phase(
        self,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        lifecycle_manager.register_startup_hook("a", lambda: None)

        with pytest.raises(HookAlreadyRegisteredError):
            lifecycle_manager.register_startup_hook("a", lambda: None)

    def test_same_name_allowed_across_different_phases(
        self,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        lifecycle_manager.register_startup_hook("a", lambda: None)
        lifecycle_manager.register_shutdown_hook("a", lambda: None)


# ---------------------------------------------------------------------
# initialize()
# ---------------------------------------------------------------------


class TestInitialize:
    def test_runs_initialize_hooks(
        self,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        calls: list[str] = []
        lifecycle_manager.register_initialize_hook(
            "load-config", lambda: calls.append("load-config")
        )

        lifecycle_manager.initialize()

        assert calls == ["load-config"]
        assert lifecycle_manager.is_initialized()

    def test_publishes_initialized_event(
        self,
        lifecycle_manager: LifecycleManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("lifecycle.initialized", subscriber)

        lifecycle_manager.initialize()

        assert len(subscriber.received) == 1
        assert isinstance(subscriber.received[0], LifecycleInitializedEvent)

    def test_cannot_initialize_twice(
        self,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        lifecycle_manager.initialize()

        with pytest.raises(AlreadyInitializedError):
            lifecycle_manager.initialize()

    def test_hook_failure_raises_lifecycle_hook_error(
        self,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        def _boom() -> None:
            raise RuntimeError("boom")

        lifecycle_manager.register_initialize_hook("boom", _boom)

        with pytest.raises(LifecycleHookError) as excinfo:
            lifecycle_manager.initialize()

        assert isinstance(excinfo.value.__cause__, RuntimeError)
        assert not lifecycle_manager.is_initialized()


# ---------------------------------------------------------------------
# start()
# ---------------------------------------------------------------------


class TestStart:
    def test_requires_initialization(
        self,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        with pytest.raises(NotInitializedError):
            lifecycle_manager.start()

    def test_starts_and_runs_hooks_in_order(
        self,
        lifecycle_manager: LifecycleManager,
        state_manager: StateManager,
    ) -> None:
        calls: list[str] = []
        lifecycle_manager.register_startup_hook(
            "first", lambda: calls.append("first")
        )
        lifecycle_manager.register_startup_hook(
            "second", lambda: calls.append("second")
        )

        lifecycle_manager.initialize()
        lifecycle_manager.start()

        assert calls == ["first", "second"]
        assert state_manager.get_lifecycle_state() is LifecycleState.RUNNING

    def test_publishes_started_event(
        self,
        lifecycle_manager: LifecycleManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("lifecycle.started", subscriber)

        lifecycle_manager.initialize()
        lifecycle_manager.start()

        assert len(subscriber.received) == 1
        assert isinstance(subscriber.received[0], LifecycleStartedEvent)

    def test_cannot_start_when_already_running(
        self,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        lifecycle_manager.initialize()
        lifecycle_manager.start()

        with pytest.raises(InvalidLifecycleTransitionError):
            lifecycle_manager.start()

    def test_start_failure_reverts_to_stopped_and_publishes_event(
        self,
        lifecycle_manager: LifecycleManager,
        state_manager: StateManager,
        event_bus: EventBus,
    ) -> None:
        failed_subscriber = RecordingSubscriber()
        event_bus.subscribe("lifecycle.start_failed", failed_subscriber)

        def _boom() -> None:
            raise RuntimeError("boom")

        lifecycle_manager.register_startup_hook("boom", _boom)
        lifecycle_manager.initialize()

        with pytest.raises(LifecycleHookError):
            lifecycle_manager.start()

        assert state_manager.get_lifecycle_state() is LifecycleState.STOPPED
        assert len(failed_subscriber.received) == 1
        assert isinstance(
            failed_subscriber.received[0], LifecycleStartFailedEvent
        )


# ---------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------


class TestStop:
    def test_requires_running_state(
        self,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        with pytest.raises(InvalidLifecycleTransitionError):
            lifecycle_manager.stop()

    def test_stops_and_runs_hooks_in_reverse_order(
        self,
        lifecycle_manager: LifecycleManager,
        state_manager: StateManager,
    ) -> None:
        calls: list[str] = []
        lifecycle_manager.register_shutdown_hook(
            "first", lambda: calls.append("first")
        )
        lifecycle_manager.register_shutdown_hook(
            "second", lambda: calls.append("second")
        )

        lifecycle_manager.initialize()
        lifecycle_manager.start()
        lifecycle_manager.stop()

        assert calls == ["second", "first"]
        assert state_manager.get_lifecycle_state() is LifecycleState.STOPPED

    def test_publishes_stopped_event(
        self,
        lifecycle_manager: LifecycleManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("lifecycle.stopped", subscriber)

        lifecycle_manager.initialize()
        lifecycle_manager.start()
        lifecycle_manager.stop()

        assert len(subscriber.received) == 1
        assert isinstance(subscriber.received[0], LifecycleStoppedEvent)

    def test_stop_is_best_effort_despite_hook_failure(
        self,
        lifecycle_manager: LifecycleManager,
        state_manager: StateManager,
    ) -> None:
        calls: list[str] = []

        def _boom() -> None:
            raise RuntimeError("boom")

        lifecycle_manager.register_shutdown_hook("boom", _boom)
        lifecycle_manager.register_shutdown_hook(
            "cleanup", lambda: calls.append("cleanup")
        )

        lifecycle_manager.initialize()
        lifecycle_manager.start()
        lifecycle_manager.stop()

        assert calls == ["cleanup"]
        assert state_manager.get_lifecycle_state() is LifecycleState.STOPPED


# ---------------------------------------------------------------------
# restart()
# ---------------------------------------------------------------------


class TestRestart:
    def test_restart_stops_and_starts(
        self,
        lifecycle_manager: LifecycleManager,
        state_manager: StateManager,
    ) -> None:
        calls: list[str] = []
        lifecycle_manager.register_startup_hook(
            "startup", lambda: calls.append("startup")
        )
        lifecycle_manager.register_shutdown_hook(
            "shutdown", lambda: calls.append("shutdown")
        )

        lifecycle_manager.initialize()
        lifecycle_manager.start()

        lifecycle_manager.restart()

        assert calls == ["startup", "shutdown", "startup"]
        assert state_manager.get_lifecycle_state() is LifecycleState.RUNNING

    def test_restart_requires_running_state(
        self,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        lifecycle_manager.initialize()

        with pytest.raises(InvalidLifecycleTransitionError):
            lifecycle_manager.restart()


# ---------------------------------------------------------------------
# reload()
# ---------------------------------------------------------------------


class TestReload:
    def test_requires_running_state(
        self,
        lifecycle_manager: LifecycleManager,
    ) -> None:
        with pytest.raises(InvalidLifecycleTransitionError):
            lifecycle_manager.reload()

    def test_runs_reload_hooks(
        self,
        lifecycle_manager: LifecycleManager,
        state_manager: StateManager,
    ) -> None:
        calls: list[str] = []
        lifecycle_manager.register_reload_hook(
            "reload-config", lambda: calls.append("reload-config")
        )

        lifecycle_manager.initialize()
        lifecycle_manager.start()
        lifecycle_manager.reload()

        assert calls == ["reload-config"]
        assert state_manager.get_lifecycle_state() is LifecycleState.RUNNING

    def test_publishes_reloaded_event(
        self,
        lifecycle_manager: LifecycleManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("lifecycle.reloaded", subscriber)

        lifecycle_manager.initialize()
        lifecycle_manager.start()
        lifecycle_manager.reload()

        assert len(subscriber.received) == 1
        assert isinstance(subscriber.received[0], LifecycleReloadedEvent)

    def test_reload_failure_publishes_failed_event(
        self,
        lifecycle_manager: LifecycleManager,
        event_bus: EventBus,
    ) -> None:
        failed_subscriber = RecordingSubscriber()
        event_bus.subscribe("lifecycle.reload_failed", failed_subscriber)

        def _boom() -> None:
            raise RuntimeError("boom")

        lifecycle_manager.register_reload_hook("boom", _boom)

        lifecycle_manager.initialize()
        lifecycle_manager.start()

        with pytest.raises(LifecycleHookError):
            lifecycle_manager.reload()

        assert len(failed_subscriber.received) == 1
        assert isinstance(
            failed_subscriber.received[0], LifecycleReloadFailedEvent
        )
