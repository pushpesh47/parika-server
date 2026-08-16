"""
Unit tests for WorkspacePermissionManager.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.permission_manager.permission_manager import PermissionManager
from parika.core.permission_manager.workspace_events import (
    WorkspacePermissionEvaluatedEvent,
    WorkspaceTrustedEvent,
)
from parika.core.permission_manager.workspace_operation import WorkspaceOperation
from parika.core.permission_manager.workspace_permission_manager import (
    WorkspacePermissionManager,
)
from parika.core.permission_manager.workspace_permission_scope import (
    WorkspacePermissionScope,
)


class _FakeLogger:
    def get_logger(self, name: str) -> logging.Logger:
        return logging.getLogger(name)


class RecordingSubscriber:
    def __init__(self) -> None:
        self.received: list[Any] = []

    def __call__(self, payload: Any) -> None:
        self.received.append(payload)


class _FakePrompt:
    def __init__(self, scope: WorkspacePermissionScope) -> None:
        self.scope = scope
        self.calls: list[tuple[Path, WorkspaceOperation, str | None]] = []

    def request_decision(
        self,
        *,
        workspace: Path,
        operation: WorkspaceOperation,
        reason: str | None,
    ) -> WorkspacePermissionScope:
        self.calls.append((workspace, operation, reason))
        return self.scope


class _BlockingPrompt:
    def __init__(self, scope: WorkspacePermissionScope) -> None:
        self.scope = scope
        self.call_count = 0
        self._lock = threading.Lock()
        self.entered_event = threading.Event()
        self.release_event = threading.Event()

    def request_decision(
        self,
        *,
        workspace: Path,
        operation: WorkspaceOperation,
        reason: str | None,
    ) -> WorkspacePermissionScope:
        with self._lock:
            self.call_count += 1

        self.entered_event.set()
        self.release_event.wait(timeout=5)

        return self.scope


class _FailingTrustWriter:
    def add_trusted_workspace(self, workspace: Path) -> None:
        raise RuntimeError("disk is full")


class _RecordingTrustWriter:
    def __init__(self) -> None:
        self.persisted: list[Path] = []

    def add_trusted_workspace(self, workspace: Path) -> None:
        self.persisted.append(workspace)


@pytest.fixture
def logger() -> _FakeLogger:
    return _FakeLogger()


@pytest.fixture
def event_bus(logger: _FakeLogger) -> EventBus:
    return EventBus(logger=logger)  # type: ignore[arg-type]


@pytest.fixture
def permission_manager(event_bus: EventBus, logger: _FakeLogger) -> PermissionManager:
    return PermissionManager(event_bus=event_bus, logger=logger)  # type: ignore[arg-type]


def _empty_configuration() -> Configuration:
    configuration = Configuration()
    configuration._config = {}  # noqa: SLF001
    return configuration


def _build_manager(
    *,
    permission_manager: PermissionManager,
    event_bus: EventBus,
    logger: _FakeLogger,
    configuration: Configuration | None = None,
    prompt: Any = None,
    trust_writer: Any = None,
) -> WorkspacePermissionManager:
    return WorkspacePermissionManager(
        permission_manager=permission_manager,
        configuration=configuration or _empty_configuration(),
        event_bus=event_bus,
        logger=logger,  # type: ignore[arg-type]
        prompt=prompt,
        trust_writer=trust_writer,
    )


class TestReadIsAlwaysAuthorized:
    def test_read_never_prompts_and_is_always_authorized(
        self,
        permission_manager: PermissionManager,
        event_bus: EventBus,
        logger: _FakeLogger,
        tmp_path: Path,
    ) -> None:
        prompt = _FakePrompt(WorkspacePermissionScope.DENY)
        manager = _build_manager(
            permission_manager=permission_manager,
            event_bus=event_bus,
            logger=logger,
            prompt=prompt,
        )

        decision = manager.check(tmp_path / "a.txt", WorkspaceOperation.READ)

        assert decision.authorized is True
        assert prompt.calls == []


class TestTrustedWorkspaceFastPath:
    def test_trusted_workspace_authorizes_without_prompting(
        self,
        permission_manager: PermissionManager,
        event_bus: EventBus,
        logger: _FakeLogger,
        tmp_path: Path,
    ) -> None:
        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "filesystem": {"trusted_workspaces": [str(tmp_path)]},
            "workspace": {"default_workspace": ""},
        }
        prompt = _FakePrompt(WorkspacePermissionScope.DENY)
        manager = _build_manager(
            permission_manager=permission_manager,
            event_bus=event_bus,
            logger=logger,
            configuration=configuration,
            prompt=prompt,
        )

        decision = manager.check(
            tmp_path / "sub" / "a.txt", WorkspaceOperation.WRITE
        )

        assert decision.authorized is True
        assert prompt.calls == []

    def test_default_workspace_is_included_automatically(
        self,
        permission_manager: PermissionManager,
        event_bus: EventBus,
        logger: _FakeLogger,
        tmp_path: Path,
    ) -> None:
        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "filesystem": {"trusted_workspaces": []},
            "workspace": {"default_workspace": str(tmp_path)},
        }
        manager = _build_manager(
            permission_manager=permission_manager,
            event_bus=event_bus,
            logger=logger,
            configuration=configuration,
        )

        assert tmp_path.resolve() in manager.trusted_workspaces()
        assert manager.is_trusted(tmp_path / "sub" / "a.txt")

    def test_legacy_allowed_roots_used_when_trusted_workspaces_absent(
        self,
        permission_manager: PermissionManager,
        event_bus: EventBus,
        logger: _FakeLogger,
        tmp_path: Path,
    ) -> None:
        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "filesystem": {"allowed_roots": [str(tmp_path)]},
            "workspace": {"default_workspace": ""},
        }
        manager = _build_manager(
            permission_manager=permission_manager,
            event_bus=event_bus,
            logger=logger,
            configuration=configuration,
        )

        assert manager.is_trusted(tmp_path / "a.txt")


class TestPermissionScopes:
    def test_once_scope_authorizes_but_does_not_persist(
        self,
        permission_manager: PermissionManager,
        event_bus: EventBus,
        logger: _FakeLogger,
        tmp_path: Path,
    ) -> None:
        prompt = _FakePrompt(WorkspacePermissionScope.ONCE)
        manager = _build_manager(
            permission_manager=permission_manager,
            event_bus=event_bus,
            logger=logger,
            prompt=prompt,
        )

        first = manager.check(tmp_path / "a.txt", WorkspaceOperation.WRITE)
        second = manager.check(tmp_path / "a.txt", WorkspaceOperation.WRITE)

        assert first.authorized is True
        assert second.authorized is True
        assert len(prompt.calls) == 2

    def test_session_scope_persists_for_the_process(
        self,
        permission_manager: PermissionManager,
        event_bus: EventBus,
        logger: _FakeLogger,
        tmp_path: Path,
    ) -> None:
        prompt = _FakePrompt(WorkspacePermissionScope.SESSION)
        manager = _build_manager(
            permission_manager=permission_manager,
            event_bus=event_bus,
            logger=logger,
            prompt=prompt,
        )

        first = manager.check(tmp_path / "a.txt", WorkspaceOperation.WRITE)
        second = manager.check(tmp_path / "a.txt", WorkspaceOperation.WRITE)

        assert first.authorized is True
        assert second.authorized is True
        assert len(prompt.calls) == 1

    def test_session_grant_is_namespaced_as_subject_id(
        self,
        permission_manager: PermissionManager,
        event_bus: EventBus,
        logger: _FakeLogger,
        tmp_path: Path,
    ) -> None:
        prompt = _FakePrompt(WorkspacePermissionScope.SESSION)
        manager = _build_manager(
            permission_manager=permission_manager,
            event_bus=event_bus,
            logger=logger,
            prompt=prompt,
        )

        manager.check(tmp_path / "a.txt", WorkspaceOperation.WRITE)

        expected_subject = f"workspace:{tmp_path.resolve()}"
        assert permission_manager.contains(expected_subject, "write")

    def test_permanent_scope_persists_and_writes_through_trust_writer(
        self,
        permission_manager: PermissionManager,
        event_bus: EventBus,
        logger: _FakeLogger,
        tmp_path: Path,
    ) -> None:
        prompt = _FakePrompt(WorkspacePermissionScope.PERMANENT)
        trust_writer = _RecordingTrustWriter()
        manager = _build_manager(
            permission_manager=permission_manager,
            event_bus=event_bus,
            logger=logger,
            prompt=prompt,
            trust_writer=trust_writer,
        )

        decision = manager.check(tmp_path / "a.txt", WorkspaceOperation.WRITE)

        assert decision.authorized is True
        assert trust_writer.persisted == [tmp_path.resolve()]
        assert manager.is_trusted(tmp_path / "a.txt")

        # A later request for the same workspace never prompts again,
        # since it is now unconditionally trusted.
        manager.check(tmp_path / "b.txt", WorkspaceOperation.DELETE)
        assert len(prompt.calls) == 1

    def test_permanent_scope_still_authorizes_when_persistence_fails(
        self,
        permission_manager: PermissionManager,
        event_bus: EventBus,
        logger: _FakeLogger,
        tmp_path: Path,
    ) -> None:
        prompt = _FakePrompt(WorkspacePermissionScope.PERMANENT)
        manager = _build_manager(
            permission_manager=permission_manager,
            event_bus=event_bus,
            logger=logger,
            prompt=prompt,
            trust_writer=_FailingTrustWriter(),
        )

        decision = manager.check(tmp_path / "a.txt", WorkspaceOperation.WRITE)

        assert decision.authorized is True
        assert manager.is_trusted(tmp_path / "a.txt")

    def test_deny_scope_is_not_persisted_and_reprompts(
        self,
        permission_manager: PermissionManager,
        event_bus: EventBus,
        logger: _FakeLogger,
        tmp_path: Path,
    ) -> None:
        prompt = _FakePrompt(WorkspacePermissionScope.DENY)
        manager = _build_manager(
            permission_manager=permission_manager,
            event_bus=event_bus,
            logger=logger,
            prompt=prompt,
        )

        first = manager.check(tmp_path / "a.txt", WorkspaceOperation.WRITE)
        second = manager.check(tmp_path / "a.txt", WorkspaceOperation.WRITE)

        assert first.authorized is False
        assert second.authorized is False
        assert len(prompt.calls) == 2

    def test_switching_from_once_to_permanent_replaces_the_grant(
        self,
        permission_manager: PermissionManager,
        event_bus: EventBus,
        logger: _FakeLogger,
        tmp_path: Path,
    ) -> None:
        prompt = _FakePrompt(WorkspacePermissionScope.ONCE)
        manager = _build_manager(
            permission_manager=permission_manager,
            event_bus=event_bus,
            logger=logger,
            prompt=prompt,
        )
        manager.check(tmp_path / "a.txt", WorkspaceOperation.WRITE)

        prompt.scope = WorkspacePermissionScope.SESSION
        manager.check(tmp_path / "a.txt", WorkspaceOperation.WRITE)

        prompt.scope = WorkspacePermissionScope.DENY
        third = manager.check(tmp_path / "a.txt", WorkspaceOperation.WRITE)

        assert third.authorized is True
        assert len(prompt.calls) == 2


class TestNoPromptFailsClosed:
    def test_missing_prompt_denies_by_default(
        self,
        permission_manager: PermissionManager,
        event_bus: EventBus,
        logger: _FakeLogger,
        tmp_path: Path,
    ) -> None:
        manager = _build_manager(
            permission_manager=permission_manager,
            event_bus=event_bus,
            logger=logger,
        )

        decision = manager.check(tmp_path / "a.txt", WorkspaceOperation.WRITE)

        assert decision.authorized is False
        assert decision.scope_applied is WorkspacePermissionScope.DENY


class TestWorkspaceResolution:
    def test_resolves_to_directory_containing_a_nonexistent_file(
        self,
        permission_manager: PermissionManager,
        event_bus: EventBus,
        logger: _FakeLogger,
        tmp_path: Path,
    ) -> None:
        prompt = _FakePrompt(WorkspacePermissionScope.ONCE)
        manager = _build_manager(
            permission_manager=permission_manager,
            event_bus=event_bus,
            logger=logger,
            prompt=prompt,
        )

        manager.check(tmp_path / "brand_new.txt", WorkspaceOperation.WRITE)

        assert prompt.calls[0][0] == tmp_path.resolve()

    def test_resolves_to_the_directory_itself_when_it_already_exists(
        self,
        permission_manager: PermissionManager,
        event_bus: EventBus,
        logger: _FakeLogger,
        tmp_path: Path,
    ) -> None:
        target_dir = tmp_path / "existing_dir"
        target_dir.mkdir()

        prompt = _FakePrompt(WorkspacePermissionScope.ONCE)
        manager = _build_manager(
            permission_manager=permission_manager,
            event_bus=event_bus,
            logger=logger,
            prompt=prompt,
        )

        manager.check(target_dir, WorkspaceOperation.EXECUTE)

        assert prompt.calls[0][0] == target_dir.resolve()


class TestConcurrentRequestCoalescing:
    def test_only_one_prompt_is_shown_for_concurrent_requests(
        self,
        permission_manager: PermissionManager,
        event_bus: EventBus,
        logger: _FakeLogger,
        tmp_path: Path,
    ) -> None:
        prompt = _BlockingPrompt(WorkspacePermissionScope.SESSION)
        manager = _build_manager(
            permission_manager=permission_manager,
            event_bus=event_bus,
            logger=logger,
            prompt=prompt,
        )

        results: list[Any] = []
        results_lock = threading.Lock()

        def worker() -> None:
            decision = manager.check(
                tmp_path / "shared.txt", WorkspaceOperation.WRITE
            )
            with results_lock:
                results.append(decision)

        first_thread = threading.Thread(target=worker)
        first_thread.start()

        assert prompt.entered_event.wait(timeout=5)

        second_thread = threading.Thread(target=worker)
        second_thread.start()

        # Give the second thread a chance to reach the coalescing wait.
        time.sleep(0.1)

        prompt.release_event.set()

        first_thread.join(timeout=5)
        second_thread.join(timeout=5)

        assert prompt.call_count == 1
        assert len(results) == 2
        assert all(result.authorized for result in results)


class TestEvents:
    def test_check_publishes_evaluated_event(
        self,
        permission_manager: PermissionManager,
        event_bus: EventBus,
        logger: _FakeLogger,
        tmp_path: Path,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("workspace_permission.evaluated", subscriber)

        manager = _build_manager(
            permission_manager=permission_manager,
            event_bus=event_bus,
            logger=logger,
        )
        manager.check(tmp_path / "a.txt", WorkspaceOperation.READ)

        assert len(subscriber.received) == 1
        assert isinstance(subscriber.received[0], WorkspacePermissionEvaluatedEvent)

    def test_permanent_scope_publishes_trusted_event(
        self,
        permission_manager: PermissionManager,
        event_bus: EventBus,
        logger: _FakeLogger,
        tmp_path: Path,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("workspace_permission.trusted", subscriber)

        prompt = _FakePrompt(WorkspacePermissionScope.PERMANENT)
        manager = _build_manager(
            permission_manager=permission_manager,
            event_bus=event_bus,
            logger=logger,
            prompt=prompt,
        )
        manager.check(tmp_path / "a.txt", WorkspaceOperation.WRITE)

        assert len(subscriber.received) == 1
        assert isinstance(subscriber.received[0], WorkspaceTrustedEvent)
        assert subscriber.received[0].workspace == tmp_path.resolve()
