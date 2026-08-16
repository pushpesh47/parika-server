"""
Unit tests for UpdateManager.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from parika.core.event_bus.event_bus import EventBus
from parika.core.update_manager.events import (
    MigrationAppliedEvent,
    TargetRegisteredEvent,
    TargetUnregisteredEvent,
    UpdateAppliedEvent,
    UpdateAvailableEvent,
    UpdateFailedEvent,
    UpdateUpToDateEvent,
)
from parika.core.update_manager.exceptions import (
    InvalidUpdateTargetError,
    MigrationAlreadyRegisteredError,
    MigrationError,
    TargetAlreadyRegisteredError,
    TargetNotFoundError,
    UpdateApplyError,
    UpdateNotAvailableError,
)
from parika.core.update_manager.update_info import UpdateInfo
from parika.core.update_manager.update_manager import UpdateManager
from parika.core.update_manager.update_status import UpdateStatus


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
def update_manager(event_bus: EventBus) -> UpdateManager:
    return UpdateManager(event_bus=event_bus, logger=_FakeLogger())  # type: ignore[arg-type]


# ---------------------------------------------------------------------
# register_target() / unregister_target() / registry
# ---------------------------------------------------------------------


class TestTargetRegistry:
    def test_registers_target(
        self,
        update_manager: UpdateManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("update.target.registered", subscriber)

        update_manager.register_target(
            "core",
            check=lambda: None,
            apply=lambda info: None,
            current_version="1.0.0",
        )

        record = update_manager.get("core")
        assert record.status is UpdateStatus.UNKNOWN
        assert record.current_version == "1.0.0"
        assert len(subscriber.received) == 1
        assert isinstance(subscriber.received[0], TargetRegisteredEvent)

    def test_rejects_duplicate_registration(
        self,
        update_manager: UpdateManager,
    ) -> None:
        update_manager.register_target(
            "core", check=lambda: None, apply=lambda info: None
        )

        with pytest.raises(TargetAlreadyRegisteredError):
            update_manager.register_target(
                "core", check=lambda: None, apply=lambda info: None
            )

    def test_rejects_non_callable_check_or_apply(
        self,
        update_manager: UpdateManager,
    ) -> None:
        with pytest.raises(InvalidUpdateTargetError):
            update_manager.register_target(
                "core",
                check="not-callable",  # type: ignore[arg-type]
                apply=lambda info: None,
            )

    def test_unregister_removes_target(
        self,
        update_manager: UpdateManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("update.target.unregistered", subscriber)

        update_manager.register_target(
            "core", check=lambda: None, apply=lambda info: None
        )
        update_manager.unregister_target("core")

        assert not update_manager.contains("core")
        assert len(subscriber.received) == 1
        assert isinstance(subscriber.received[0], TargetUnregisteredEvent)

    def test_unregister_raises_when_missing(
        self,
        update_manager: UpdateManager,
    ) -> None:
        with pytest.raises(TargetNotFoundError):
            update_manager.unregister_target("missing")

    def test_get_raises_when_missing(
        self,
        update_manager: UpdateManager,
    ) -> None:
        with pytest.raises(TargetNotFoundError):
            update_manager.get("missing")

    def test_get_all_and_count(
        self,
        update_manager: UpdateManager,
    ) -> None:
        update_manager.register_target(
            "core", check=lambda: None, apply=lambda info: None
        )
        update_manager.register_target(
            "provider:ollama", check=lambda: None, apply=lambda info: None
        )

        assert update_manager.count() == 2
        assert set(update_manager.get_all()) == {"core", "provider:ollama"}


# ---------------------------------------------------------------------
# check() / check_all()
# ---------------------------------------------------------------------


class TestCheck:
    def test_check_raises_when_missing(
        self,
        update_manager: UpdateManager,
    ) -> None:
        with pytest.raises(TargetNotFoundError):
            update_manager.check("missing")

    def test_check_reports_up_to_date(
        self,
        update_manager: UpdateManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("update.up_to_date", subscriber)

        update_manager.register_target(
            "core", check=lambda: None, apply=lambda info: None
        )

        record = update_manager.check("core")

        assert record.status is UpdateStatus.UP_TO_DATE
        assert record.last_checked_at is not None
        assert len(subscriber.received) == 1
        assert isinstance(subscriber.received[0], UpdateUpToDateEvent)

    def test_check_reports_update_available(
        self,
        update_manager: UpdateManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("update.available", subscriber)

        info = UpdateInfo(
            current_version="1.0.0", available_version="1.1.0"
        )
        update_manager.register_target(
            "core",
            check=lambda: info,
            apply=lambda received_info: None,
            current_version="1.0.0",
        )

        record = update_manager.check("core")

        assert record.status is UpdateStatus.UPDATE_AVAILABLE
        assert record.pending_update is info
        assert len(subscriber.received) == 1
        assert isinstance(subscriber.received[0], UpdateAvailableEvent)

    def test_check_exception_marks_failed_without_raising(
        self,
        update_manager: UpdateManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("update.failed", subscriber)

        def _boom() -> None:
            raise RuntimeError("boom")

        update_manager.register_target(
            "core", check=_boom, apply=lambda info: None
        )

        record = update_manager.check("core")

        assert record.status is UpdateStatus.FAILED
        assert isinstance(record.failure, RuntimeError)
        assert len(subscriber.received) == 1
        assert isinstance(subscriber.received[0], UpdateFailedEvent)

    def test_check_all_checks_every_target(
        self,
        update_manager: UpdateManager,
    ) -> None:
        update_manager.register_target(
            "a", check=lambda: None, apply=lambda info: None
        )
        update_manager.register_target(
            "b",
            check=lambda: UpdateInfo(
                current_version="1.0", available_version="2.0"
            ),
            apply=lambda info: None,
        )

        results = update_manager.check_all()

        assert results["a"].status is UpdateStatus.UP_TO_DATE
        assert results["b"].status is UpdateStatus.UPDATE_AVAILABLE


# ---------------------------------------------------------------------
# apply()
# ---------------------------------------------------------------------


class TestApply:
    def test_apply_raises_when_no_pending_update(
        self,
        update_manager: UpdateManager,
    ) -> None:
        update_manager.register_target(
            "core", check=lambda: None, apply=lambda info: None
        )
        update_manager.check("core")

        with pytest.raises(UpdateNotAvailableError):
            update_manager.apply("core")

    def test_apply_raises_when_target_missing(
        self,
        update_manager: UpdateManager,
    ) -> None:
        with pytest.raises(TargetNotFoundError):
            update_manager.apply("missing")

    def test_apply_updates_target_on_success(
        self,
        update_manager: UpdateManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("update.applied", subscriber)

        calls: list[UpdateInfo] = []
        info = UpdateInfo(
            current_version="1.0.0", available_version="1.1.0"
        )

        update_manager.register_target(
            "core",
            check=lambda: info,
            apply=lambda received: calls.append(received),
            current_version="1.0.0",
        )
        update_manager.check("core")

        record = update_manager.apply("core")

        assert calls == [info]
        assert record.status is UpdateStatus.UPDATED
        assert record.current_version == "1.1.0"
        assert record.pending_update is None
        assert record.last_updated_at is not None
        assert len(subscriber.received) == 1
        assert isinstance(subscriber.received[0], UpdateAppliedEvent)

    def test_apply_failure_marks_target_failed(
        self,
        update_manager: UpdateManager,
        event_bus: EventBus,
    ) -> None:
        failed = RecordingSubscriber()
        event_bus.subscribe("update.failed", failed)

        info = UpdateInfo(
            current_version="1.0.0", available_version="1.1.0"
        )

        def _boom(received: UpdateInfo) -> None:
            raise RuntimeError("boom")

        update_manager.register_target(
            "core", check=lambda: info, apply=_boom
        )
        update_manager.check("core")

        with pytest.raises(UpdateApplyError) as excinfo:
            update_manager.apply("core")

        assert isinstance(excinfo.value.__cause__, RuntimeError)

        record = update_manager.get("core")
        assert record.status is UpdateStatus.FAILED
        assert len(failed.received) == 1


# ---------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------


class TestMigrations:
    def test_run_migrations_runs_in_registration_order(
        self,
        update_manager: UpdateManager,
    ) -> None:
        calls: list[str] = []

        update_manager.register_migration(
            "1.1.0", lambda: calls.append("1.1.0")
        )
        update_manager.register_migration(
            "1.2.0", lambda: calls.append("1.2.0")
        )

        applied = update_manager.run_migrations()

        assert calls == ["1.1.0", "1.2.0"]
        assert applied == ("1.1.0", "1.2.0")

    def test_run_migrations_is_idempotent(
        self,
        update_manager: UpdateManager,
    ) -> None:
        calls: list[str] = []

        update_manager.register_migration(
            "1.1.0", lambda: calls.append("1.1.0")
        )

        update_manager.run_migrations()
        second_run = update_manager.run_migrations()

        assert calls == ["1.1.0"]
        assert second_run == ()

    def test_rejects_duplicate_migration_version(
        self,
        update_manager: UpdateManager,
    ) -> None:
        update_manager.register_migration("1.1.0", lambda: None)

        with pytest.raises(MigrationAlreadyRegisteredError):
            update_manager.register_migration("1.1.0", lambda: None)

    def test_publishes_migration_applied_event(
        self,
        update_manager: UpdateManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("update.migration.applied", subscriber)

        update_manager.register_migration("1.1.0", lambda: None)
        update_manager.run_migrations()

        assert len(subscriber.received) == 1
        assert isinstance(subscriber.received[0], MigrationAppliedEvent)

    def test_migration_failure_stops_remaining_migrations(
        self,
        update_manager: UpdateManager,
    ) -> None:
        calls: list[str] = []

        def _boom() -> None:
            raise RuntimeError("boom")

        update_manager.register_migration(
            "1.1.0", lambda: calls.append("1.1.0")
        )
        update_manager.register_migration("1.2.0", _boom)
        update_manager.register_migration(
            "1.3.0", lambda: calls.append("1.3.0")
        )

        with pytest.raises(MigrationError):
            update_manager.run_migrations()

        assert calls == ["1.1.0"]
