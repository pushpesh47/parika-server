"""
Unit tests for HealthManager.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from parika.core.event_bus.event_bus import EventBus
from parika.core.health_manager.events import (
    ComponentHealthChangedEvent,
    ComponentRecoveryFailedEvent,
    ComponentRecoveryTriggeredEvent,
    ComponentRegisteredEvent,
    ComponentUnregisteredEvent,
)
from parika.core.health_manager.exceptions import (
    ComponentAlreadyRegisteredError,
    ComponentNotFoundError,
    InvalidHealthCheckError,
)
from parika.core.health_manager.health_check_result import (
    HealthCheckResult,
)
from parika.core.health_manager.health_manager import HealthManager
from parika.core.health_manager.health_status import HealthStatus


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
def health_manager(event_bus: EventBus) -> HealthManager:
    return HealthManager(event_bus=event_bus, logger=_FakeLogger())  # type: ignore[arg-type]


# ---------------------------------------------------------------------
# register() / unregister()
# ---------------------------------------------------------------------


class TestRegistration:
    def test_registers_component(
        self,
        health_manager: HealthManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("health.component.registered", subscriber)

        health_manager.register("provider.ollama")

        assert health_manager.contains("provider.ollama")
        assert (
            health_manager.get("provider.ollama").status
            is HealthStatus.UNKNOWN
        )
        assert len(subscriber.received) == 1
        assert isinstance(subscriber.received[0], ComponentRegisteredEvent)

    def test_rejects_duplicate_registration(
        self,
        health_manager: HealthManager,
    ) -> None:
        health_manager.register("provider.ollama")

        with pytest.raises(ComponentAlreadyRegisteredError):
            health_manager.register("provider.ollama")

    def test_rejects_non_callable_check(
        self,
        health_manager: HealthManager,
    ) -> None:
        with pytest.raises(InvalidHealthCheckError):
            health_manager.register(
                "provider.ollama",
                check="not-callable",  # type: ignore[arg-type]
            )

    def test_rejects_non_callable_recovery(
        self,
        health_manager: HealthManager,
    ) -> None:
        with pytest.raises(InvalidHealthCheckError):
            health_manager.register(
                "provider.ollama",
                recovery="not-callable",  # type: ignore[arg-type]
            )

    def test_unregister_removes_component(
        self,
        health_manager: HealthManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("health.component.unregistered", subscriber)

        health_manager.register("provider.ollama")
        health_manager.unregister("provider.ollama")

        assert not health_manager.contains("provider.ollama")
        assert len(subscriber.received) == 1
        assert isinstance(
            subscriber.received[0], ComponentUnregisteredEvent
        )

    def test_unregister_raises_when_missing(
        self,
        health_manager: HealthManager,
    ) -> None:
        with pytest.raises(ComponentNotFoundError):
            health_manager.unregister("missing")


# ---------------------------------------------------------------------
# run_check() / run_all_checks()
# ---------------------------------------------------------------------


class TestRunCheck:
    def test_runs_registered_check(
        self,
        health_manager: HealthManager,
    ) -> None:
        health_manager.register(
            "provider.ollama",
            check=lambda: HealthCheckResult(status=HealthStatus.HEALTHY),
        )

        result = health_manager.run_check("provider.ollama")

        assert result.status is HealthStatus.HEALTHY

    def test_raises_when_component_missing(
        self,
        health_manager: HealthManager,
    ) -> None:
        with pytest.raises(ComponentNotFoundError):
            health_manager.run_check("missing")

    def test_raises_when_no_check_registered(
        self,
        health_manager: HealthManager,
    ) -> None:
        health_manager.register("provider.ollama")

        with pytest.raises(InvalidHealthCheckError):
            health_manager.run_check("provider.ollama")

    def test_check_exception_marks_unhealthy(
        self,
        health_manager: HealthManager,
    ) -> None:
        def _boom() -> HealthCheckResult:
            raise RuntimeError("boom")

        health_manager.register("provider.ollama", check=_boom)

        result = health_manager.run_check("provider.ollama")

        assert result.status is HealthStatus.UNHEALTHY

    def test_run_all_checks_runs_every_component_with_a_check(
        self,
        health_manager: HealthManager,
    ) -> None:
        health_manager.register(
            "a", check=lambda: HealthCheckResult(status=HealthStatus.HEALTHY)
        )
        health_manager.register(
            "b",
            check=lambda: HealthCheckResult(status=HealthStatus.DEGRADED),
        )
        health_manager.register("c")  # no check registered

        results = health_manager.run_all_checks()

        assert results["a"].status is HealthStatus.HEALTHY
        assert results["b"].status is HealthStatus.DEGRADED
        assert results["c"].status is HealthStatus.UNKNOWN


# ---------------------------------------------------------------------
# heartbeat()
# ---------------------------------------------------------------------


class TestHeartbeat:
    def test_records_heartbeat(
        self,
        health_manager: HealthManager,
    ) -> None:
        health_manager.register("module.web_search")

        health = health_manager.heartbeat("module.web_search")

        assert health.status is HealthStatus.HEALTHY
        assert health.last_heartbeat_at is not None

    def test_heartbeat_raises_when_missing(
        self,
        health_manager: HealthManager,
    ) -> None:
        with pytest.raises(ComponentNotFoundError):
            health_manager.heartbeat("missing")

    def test_heartbeat_can_report_unhealthy(
        self,
        health_manager: HealthManager,
    ) -> None:
        health_manager.register("module.web_search")

        health = health_manager.heartbeat(
            "module.web_search",
            status=HealthStatus.UNHEALTHY,
            message="connection lost",
        )

        assert health.status is HealthStatus.UNHEALTHY
        assert health.last_result is not None
        assert health.last_result.message == "connection lost"


# ---------------------------------------------------------------------
# Failure detection and recovery coordination
# ---------------------------------------------------------------------


class TestFailureDetectionAndRecovery:
    def test_consecutive_failures_increment_and_reset(
        self,
        health_manager: HealthManager,
    ) -> None:
        health_manager.register("provider.ollama")

        health_manager.heartbeat(
            "provider.ollama", status=HealthStatus.UNHEALTHY
        )
        health_manager.heartbeat(
            "provider.ollama", status=HealthStatus.UNHEALTHY
        )

        assert (
            health_manager.get("provider.ollama").consecutive_failures == 2
        )

        health_manager.heartbeat(
            "provider.ollama", status=HealthStatus.HEALTHY
        )

        assert (
            health_manager.get("provider.ollama").consecutive_failures == 0
        )

    def test_health_changed_event_published_on_transition(
        self,
        health_manager: HealthManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe(
            "health.component.health_changed", subscriber
        )

        health_manager.register("provider.ollama")
        health_manager.heartbeat(
            "provider.ollama", status=HealthStatus.HEALTHY
        )
        health_manager.heartbeat(
            "provider.ollama", status=HealthStatus.HEALTHY
        )

        assert len(subscriber.received) == 1
        event = subscriber.received[0]
        assert isinstance(event, ComponentHealthChangedEvent)
        assert event.previous_status is HealthStatus.UNKNOWN
        assert event.current_status is HealthStatus.HEALTHY

    def test_recovery_hook_triggered_when_unhealthy(
        self,
        health_manager: HealthManager,
        event_bus: EventBus,
    ) -> None:
        triggered = RecordingSubscriber()
        event_bus.subscribe(
            "health.component.recovery_triggered", triggered
        )

        calls: list[str] = []
        health_manager.register(
            "provider.ollama",
            recovery=lambda: calls.append("recovered"),
        )

        health_manager.heartbeat(
            "provider.ollama", status=HealthStatus.UNHEALTHY
        )

        assert calls == ["recovered"]
        assert len(triggered.received) == 1
        assert isinstance(
            triggered.received[0], ComponentRecoveryTriggeredEvent
        )

    def test_recovery_hook_failure_is_isolated(
        self,
        health_manager: HealthManager,
        event_bus: EventBus,
    ) -> None:
        failed = RecordingSubscriber()
        event_bus.subscribe("health.component.recovery_failed", failed)

        def _boom() -> None:
            raise RuntimeError("boom")

        health_manager.register("provider.ollama", recovery=_boom)

        # Should not raise.
        health_manager.heartbeat(
            "provider.ollama", status=HealthStatus.UNHEALTHY
        )

        assert len(failed.received) == 1
        assert isinstance(failed.received[0], ComponentRecoveryFailedEvent)


# ---------------------------------------------------------------------
# Registry and overall_status()
# ---------------------------------------------------------------------


class TestRegistryAndOverallStatus:
    def test_get_all_and_count(
        self,
        health_manager: HealthManager,
    ) -> None:
        health_manager.register("a")
        health_manager.register("b")

        assert health_manager.count() == 2
        assert set(health_manager.get_all()) == {"a", "b"}

    def test_overall_status_unknown_when_empty(
        self,
        health_manager: HealthManager,
    ) -> None:
        assert health_manager.overall_status() is HealthStatus.UNKNOWN

    def test_overall_status_reflects_worst_component(
        self,
        health_manager: HealthManager,
    ) -> None:
        health_manager.register("a")
        health_manager.register("b")

        health_manager.heartbeat("a", status=HealthStatus.HEALTHY)
        health_manager.heartbeat("b", status=HealthStatus.DEGRADED)

        assert health_manager.overall_status() is HealthStatus.DEGRADED

        health_manager.heartbeat("b", status=HealthStatus.UNHEALTHY)

        assert health_manager.overall_status() is HealthStatus.UNHEALTHY

    def test_overall_status_healthy_when_all_healthy(
        self,
        health_manager: HealthManager,
    ) -> None:
        health_manager.register("a")
        health_manager.heartbeat("a", status=HealthStatus.HEALTHY)

        assert health_manager.overall_status() is HealthStatus.HEALTHY
