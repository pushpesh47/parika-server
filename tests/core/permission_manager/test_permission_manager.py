"""
Unit tests for PermissionManager.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from parika.core.event_bus.event_bus import EventBus
from parika.core.permission_manager.events import (
    PermissionDeniedEvent,
    PermissionGrantedEvent,
    PermissionRevokedEvent,
)
from parika.core.permission_manager.exceptions import (
    PermissionAlreadyGrantedError,
    PermissionNotFoundError,
)
from parika.core.permission_manager.permission_manager import (
    PermissionManager,
)


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
def permission_manager(event_bus: EventBus) -> PermissionManager:
    return PermissionManager(event_bus=event_bus, logger=_FakeLogger())  # type: ignore[arg-type]


# ---------------------------------------------------------------------
# grant() / revoke() / registry
# ---------------------------------------------------------------------


class TestGrantAndRevoke:
    def test_grant_creates_record(
        self,
        permission_manager: PermissionManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("permission.granted", subscriber)

        grant = permission_manager.grant(
            "tool.web_search", "network.fetch"
        )

        assert permission_manager.contains(
            "tool.web_search", "network.fetch"
        )
        assert grant.requires_confirmation is False
        assert len(subscriber.received) == 1
        assert isinstance(subscriber.received[0], PermissionGrantedEvent)

    def test_rejects_duplicate_grant(
        self,
        permission_manager: PermissionManager,
    ) -> None:
        permission_manager.grant("tool.web_search", "network.fetch")

        with pytest.raises(PermissionAlreadyGrantedError):
            permission_manager.grant("tool.web_search", "network.fetch")

    def test_revoke_removes_record(
        self,
        permission_manager: PermissionManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("permission.revoked", subscriber)

        permission_manager.grant("tool.web_search", "network.fetch")
        permission_manager.revoke("tool.web_search", "network.fetch")

        assert not permission_manager.contains(
            "tool.web_search", "network.fetch"
        )
        assert len(subscriber.received) == 1
        assert isinstance(subscriber.received[0], PermissionRevokedEvent)

    def test_revoke_raises_when_missing(
        self,
        permission_manager: PermissionManager,
    ) -> None:
        with pytest.raises(PermissionNotFoundError):
            permission_manager.revoke("missing", "operation")

    def test_get_raises_when_missing(
        self,
        permission_manager: PermissionManager,
    ) -> None:
        with pytest.raises(PermissionNotFoundError):
            permission_manager.get("missing", "operation")

    def test_get_all_and_count(
        self,
        permission_manager: PermissionManager,
    ) -> None:
        permission_manager.grant("a", "op1")
        permission_manager.grant("b", "op2")

        assert permission_manager.count() == 2
        assert {g.subject_id for g in permission_manager.get_all()} == {
            "a",
            "b",
        }


# ---------------------------------------------------------------------
# check()
# ---------------------------------------------------------------------


class TestCheck:
    def test_denies_when_no_grant_exists(
        self,
        permission_manager: PermissionManager,
    ) -> None:
        decision = permission_manager.check("tool.web_search", "network.fetch")

        assert decision.authorized is False
        assert decision.requires_confirmation is False

    def test_authorizes_simple_grant(
        self,
        permission_manager: PermissionManager,
    ) -> None:
        permission_manager.grant("tool.web_search", "network.fetch")

        decision = permission_manager.check(
            "tool.web_search", "network.fetch"
        )

        assert decision.authorized is True
        assert decision.requires_confirmation is False

    def test_confirmation_required_grant_denied_without_confirmation(
        self,
        permission_manager: PermissionManager,
    ) -> None:
        permission_manager.grant(
            "tool.filesystem",
            "filesystem.delete",
            requires_confirmation=True,
            reason="Destructive operation.",
        )

        decision = permission_manager.check(
            "tool.filesystem", "filesystem.delete"
        )

        assert decision.authorized is False
        assert decision.requires_confirmation is True
        assert decision.reason == "Destructive operation."

    def test_confirmation_required_grant_authorized_when_confirmed(
        self,
        permission_manager: PermissionManager,
    ) -> None:
        permission_manager.grant(
            "tool.filesystem",
            "filesystem.delete",
            requires_confirmation=True,
        )

        decision = permission_manager.check(
            "tool.filesystem",
            "filesystem.delete",
            confirmed=True,
        )

        assert decision.authorized is True

    def test_confirmed_flag_ignored_when_not_required(
        self,
        permission_manager: PermissionManager,
    ) -> None:
        permission_manager.grant("tool.web_search", "network.fetch")

        decision = permission_manager.check(
            "tool.web_search",
            "network.fetch",
            confirmed=False,
        )

        assert decision.authorized is True

    def test_denied_check_publishes_event(
        self,
        permission_manager: PermissionManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("permission.denied", subscriber)

        permission_manager.check("tool.web_search", "network.fetch")

        assert len(subscriber.received) == 1
        assert isinstance(subscriber.received[0], PermissionDeniedEvent)

    def test_authorized_check_does_not_publish_denied_event(
        self,
        permission_manager: PermissionManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("permission.denied", subscriber)

        permission_manager.grant("tool.web_search", "network.fetch")
        permission_manager.check("tool.web_search", "network.fetch")

        assert subscriber.received == []

    def test_check_never_raises_for_unknown_subject(
        self,
        permission_manager: PermissionManager,
    ) -> None:
        # Should not raise despite no grant/registration existing.
        decision = permission_manager.check("unknown", "unknown.op")

        assert decision.authorized is False
