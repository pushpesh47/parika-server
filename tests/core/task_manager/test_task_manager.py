"""
Unit tests for TaskManager.

These tests exercise TaskManager in isolation. CapabilityExecutor is
replaced by a lightweight test double so that TaskManager's lifecycle
coordination logic can be verified without depending on ToolManager,
ProviderManager, or any other downstream component.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import Mock

import pytest

from parika.core.capability_executor.request import (
    CapabilityExecutionRequest,
)
from parika.core.capability_executor.response import (
    CapabilityExecutionResponse,
)
from parika.core.event_bus.event_bus import EventBus
from parika.core.task_manager.events import (
    TaskCancelledEvent,
    TaskCompletedEvent,
    TaskCreatedEvent,
    TaskFailedEvent,
    TaskPausedEvent,
    TaskResumedEvent,
    TaskStartedEvent,
)
from parika.core.task_manager.exceptions import (
    InvalidTaskRequestError,
    TaskAlreadyCompletedError,
    TaskAlreadyRunningError,
    TaskCancelledError,
    TaskExecutionError,
    TaskNotFoundError,
    TaskNotRunningError,
    TaskPausedError,
)
from parika.core.task_manager.request import TaskRequest
from parika.core.task_manager.task_manager import TaskManager
from parika.core.task_manager.task_status import TaskStatus


class _FakeLogger:
    """Minimal Logger stand-in that avoids file/console side effects."""

    def get_logger(self, name: str) -> logging.Logger:
        return logging.getLogger(name)


class _FakeCapabilityExecutor:
    """
    Test double for CapabilityExecutor.

    Allows tests to control the outcome of `execute()` without
    depending on ToolManager or ProviderManager.
    """

    def __init__(self) -> None:
        self.calls: list[CapabilityExecutionRequest] = []
        self.task_ids: list[str | None] = []
        self._result: CapabilityExecutionResponse | None = None
        self._error: BaseException | None = None

    def succeed_with(self, response: CapabilityExecutionResponse) -> None:
        self._result = response
        self._error = None

    def fail_with(self, error: BaseException) -> None:
        self._error = error
        self._result = None

    def execute(
        self,
        request: CapabilityExecutionRequest,
        *,
        task_id: str | None = None,
    ) -> CapabilityExecutionResponse:
        self.calls.append(request)
        self.task_ids.append(task_id)

        if self._error is not None:
            raise self._error

        assert self._result is not None
        return self._result


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus(logger=_FakeLogger())  # type: ignore[arg-type]


@pytest.fixture
def capability_executor() -> _FakeCapabilityExecutor:
    return _FakeCapabilityExecutor()


@pytest.fixture
def task_manager(
    event_bus: EventBus,
    capability_executor: _FakeCapabilityExecutor,
) -> TaskManager:
    return TaskManager(
        event_bus=event_bus,
        logger=_FakeLogger(),  # type: ignore[arg-type]
        capability_executor=capability_executor,  # type: ignore[arg-type]
    )


def _make_execution_request() -> CapabilityExecutionRequest:
    """Build an opaque execution request sentinel."""

    return Mock(spec=CapabilityExecutionRequest)


def _make_execution_response(
    *,
    duration_seconds: float = 0.42,
    metadata: dict[str, Any] | None = None,
) -> CapabilityExecutionResponse:
    return CapabilityExecutionResponse(
        backend_response=Mock(),
        metadata=metadata or {},
        duration_seconds=duration_seconds,
    )


class RecordingSubscriber:
    """Records every event payload it receives."""

    def __init__(self) -> None:
        self.received: list[Any] = []

    def __call__(self, payload: Any) -> None:
        self.received.append(payload)


# ---------------------------------------------------------------------
# create()
# ---------------------------------------------------------------------


class TestCreate:
    def test_creates_task_with_pending_status(
        self,
        task_manager: TaskManager,
    ) -> None:
        request = TaskRequest(capability_id="capability.echo")

        task = task_manager.create(request)

        assert task.status is TaskStatus.PENDING
        assert task.request is request
        assert task.response is None
        assert task_manager.contains(task.id)

    def test_publishes_task_created_event(
        self,
        task_manager: TaskManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("task.created", subscriber)

        request = TaskRequest(capability_id="capability.echo")
        task = task_manager.create(request)

        assert len(subscriber.received) == 1
        event = subscriber.received[0]
        assert isinstance(event, TaskCreatedEvent)
        assert event.task is task

    def test_generated_task_ids_are_unique(
        self,
        task_manager: TaskManager,
    ) -> None:
        request = TaskRequest(capability_id="capability.echo")

        first = task_manager.create(request)
        second = task_manager.create(request)

        assert first.id != second.id

    def test_rejects_invalid_request(
        self,
        task_manager: TaskManager,
    ) -> None:
        with pytest.raises(InvalidTaskRequestError):
            task_manager.create(object())  # type: ignore[arg-type]

    def test_stores_optional_linkage_fields(
        self,
        task_manager: TaskManager,
    ) -> None:
        request = TaskRequest(capability_id="capability.echo")

        task = task_manager.create(
            request,
            execution_id="execution-1",
            step_id="step-1",
            parent_task_id="parent-1",
        )

        assert task.execution_id == "execution-1"
        assert task.step_id == "step-1"
        assert task.parent_task_id == "parent-1"


# ---------------------------------------------------------------------
# get() / contains() / get_all() / count() / remove()
# ---------------------------------------------------------------------


class TestRegistry:
    def test_get_returns_registered_task(
        self,
        task_manager: TaskManager,
    ) -> None:
        request = TaskRequest(capability_id="capability.echo")
        created = task_manager.create(request)

        assert task_manager.get(created.id) is created

    def test_get_raises_when_missing(
        self,
        task_manager: TaskManager,
    ) -> None:
        with pytest.raises(TaskNotFoundError):
            task_manager.get("missing-task")

    def test_contains_reflects_registry_state(
        self,
        task_manager: TaskManager,
    ) -> None:
        assert not task_manager.contains("missing-task")

        request = TaskRequest(capability_id="capability.echo")
        task = task_manager.create(request)

        assert task_manager.contains(task.id)

    def test_get_all_and_count(
        self,
        task_manager: TaskManager,
    ) -> None:
        request = TaskRequest(capability_id="capability.echo")

        assert task_manager.count() == 0

        first = task_manager.create(request)
        second = task_manager.create(request)

        all_tasks = task_manager.get_all()

        assert task_manager.count() == 2
        assert set(all_tasks) == {first.id, second.id}

    def test_get_all_is_read_only_snapshot(
        self,
        task_manager: TaskManager,
    ) -> None:
        request = TaskRequest(capability_id="capability.echo")
        task_manager.create(request)

        all_tasks = task_manager.get_all()

        with pytest.raises(TypeError):
            all_tasks["new-key"] = object()  # type: ignore[index]

    def test_remove_deletes_task(
        self,
        task_manager: TaskManager,
    ) -> None:
        request = TaskRequest(capability_id="capability.echo")
        task = task_manager.create(request)

        task_manager.remove(task.id)

        assert not task_manager.contains(task.id)

    def test_remove_raises_when_missing(
        self,
        task_manager: TaskManager,
    ) -> None:
        with pytest.raises(TaskNotFoundError):
            task_manager.remove("missing-task")


# ---------------------------------------------------------------------
# execute() - success
# ---------------------------------------------------------------------


class TestExecuteSuccess:
    def test_executes_and_completes_task(
        self,
        task_manager: TaskManager,
        capability_executor: _FakeCapabilityExecutor,
    ) -> None:
        request = TaskRequest(capability_id="capability.echo")
        task = task_manager.create(request)

        capability_executor.succeed_with(
            _make_execution_response(duration_seconds=1.5),
        )

        result = task_manager.execute(task.id, _make_execution_request())

        assert result is task
        assert task.status is TaskStatus.COMPLETED
        assert task.started_at is not None
        assert task.completed_at is not None
        assert task.response is not None
        assert task.response.duration_seconds == 1.5

    def test_forwards_own_task_id_to_capability_executor(
        self,
        task_manager: TaskManager,
        capability_executor: _FakeCapabilityExecutor,
    ) -> None:
        """
        Phase 3.5b: TaskManager threads its own Task.id into
        CapabilityExecutor.execute() so execution events can be
        correlated back to this Task.
        """

        request = TaskRequest(capability_id="capability.echo")
        task = task_manager.create(request)

        capability_executor.succeed_with(_make_execution_response())

        task_manager.execute(task.id, _make_execution_request())

        assert capability_executor.task_ids == [task.id]

    def test_stores_backend_response_opaquely(
        self,
        task_manager: TaskManager,
        capability_executor: _FakeCapabilityExecutor,
    ) -> None:
        request = TaskRequest(capability_id="capability.echo")
        task = task_manager.create(request)

        backend_response_sentinel = Mock()
        response = CapabilityExecutionResponse(
            backend_response=backend_response_sentinel,
            metadata={"trace_id": "abc"},
            duration_seconds=0.1,
        )
        capability_executor.succeed_with(response)

        task_manager.execute(task.id, _make_execution_request())

        assert task.response is not None
        assert task.response.outputs["result"] is backend_response_sentinel
        assert task.response.metadata["trace_id"] == "abc"

    def test_publishes_started_and_completed_events(
        self,
        task_manager: TaskManager,
        capability_executor: _FakeCapabilityExecutor,
        event_bus: EventBus,
    ) -> None:
        started = RecordingSubscriber()
        completed = RecordingSubscriber()
        event_bus.subscribe("task.started", started)
        event_bus.subscribe("task.completed", completed)

        request = TaskRequest(capability_id="capability.echo")
        task = task_manager.create(request)
        capability_executor.succeed_with(_make_execution_response())

        task_manager.execute(task.id, _make_execution_request())

        assert len(started.received) == 1
        assert isinstance(started.received[0], TaskStartedEvent)
        assert len(completed.received) == 1
        assert isinstance(completed.received[0], TaskCompletedEvent)

    def test_forwards_execution_request_unchanged(
        self,
        task_manager: TaskManager,
        capability_executor: _FakeCapabilityExecutor,
    ) -> None:
        request = TaskRequest(capability_id="capability.echo")
        task = task_manager.create(request)
        capability_executor.succeed_with(_make_execution_response())

        execution_request = _make_execution_request()
        task_manager.execute(task.id, execution_request)

        assert capability_executor.calls == [execution_request]


# ---------------------------------------------------------------------
# execute() - failure and invalid state
# ---------------------------------------------------------------------


class TestExecuteFailure:
    def test_raises_task_not_found(
        self,
        task_manager: TaskManager,
    ) -> None:
        with pytest.raises(TaskNotFoundError):
            task_manager.execute("missing-task", _make_execution_request())

    def test_wraps_backend_failure(
        self,
        task_manager: TaskManager,
        capability_executor: _FakeCapabilityExecutor,
    ) -> None:
        request = TaskRequest(capability_id="capability.echo")
        task = task_manager.create(request)

        backend_error = RuntimeError("backend exploded")
        capability_executor.fail_with(backend_error)

        with pytest.raises(TaskExecutionError) as excinfo:
            task_manager.execute(task.id, _make_execution_request())

        assert excinfo.value.__cause__ is backend_error
        assert task.status is TaskStatus.FAILED
        assert task.failure is backend_error
        assert task.completed_at is not None

    def test_publishes_failed_event(
        self,
        task_manager: TaskManager,
        capability_executor: _FakeCapabilityExecutor,
        event_bus: EventBus,
    ) -> None:
        failed = RecordingSubscriber()
        event_bus.subscribe("task.failed", failed)

        request = TaskRequest(capability_id="capability.echo")
        task = task_manager.create(request)
        capability_executor.fail_with(RuntimeError("boom"))

        with pytest.raises(TaskExecutionError):
            task_manager.execute(task.id, _make_execution_request())

        assert len(failed.received) == 1
        assert isinstance(failed.received[0], TaskFailedEvent)

    def test_cannot_execute_already_running_task(
        self,
        task_manager: TaskManager,
    ) -> None:
        request = TaskRequest(capability_id="capability.echo")
        task = task_manager.create(request)
        task.status = TaskStatus.RUNNING

        with pytest.raises(TaskAlreadyRunningError):
            task_manager.execute(task.id, _make_execution_request())

    def test_cannot_execute_completed_task(
        self,
        task_manager: TaskManager,
    ) -> None:
        request = TaskRequest(capability_id="capability.echo")
        task = task_manager.create(request)
        task.status = TaskStatus.COMPLETED

        with pytest.raises(TaskAlreadyCompletedError):
            task_manager.execute(task.id, _make_execution_request())

    def test_cannot_execute_cancelled_task(
        self,
        task_manager: TaskManager,
    ) -> None:
        request = TaskRequest(capability_id="capability.echo")
        task = task_manager.create(request)
        task.status = TaskStatus.CANCELLED

        with pytest.raises(TaskCancelledError):
            task_manager.execute(task.id, _make_execution_request())

    def test_cannot_execute_paused_task(
        self,
        task_manager: TaskManager,
    ) -> None:
        request = TaskRequest(capability_id="capability.echo")
        task = task_manager.create(request)
        task.status = TaskStatus.PAUSED

        with pytest.raises(TaskPausedError):
            task_manager.execute(task.id, _make_execution_request())


# ---------------------------------------------------------------------
# retry()
# ---------------------------------------------------------------------


class TestRetry:
    def test_retries_failed_task_and_increments_retry_count(
        self,
        task_manager: TaskManager,
        capability_executor: _FakeCapabilityExecutor,
    ) -> None:
        request = TaskRequest(capability_id="capability.echo")
        task = task_manager.create(request)

        capability_executor.fail_with(RuntimeError("first failure"))
        with pytest.raises(TaskExecutionError):
            task_manager.execute(task.id, _make_execution_request())

        assert task.status is TaskStatus.FAILED

        capability_executor.succeed_with(_make_execution_response())
        result = task_manager.retry(task.id, _make_execution_request())

        assert result.status is TaskStatus.COMPLETED
        assert task.metadata["retry_count"] == 1

    def test_retry_raises_when_task_not_failed(
        self,
        task_manager: TaskManager,
    ) -> None:
        request = TaskRequest(capability_id="capability.echo")
        task = task_manager.create(request)

        with pytest.raises(TaskExecutionError):
            task_manager.retry(task.id, _make_execution_request())

    def test_retry_raises_task_not_found(
        self,
        task_manager: TaskManager,
    ) -> None:
        with pytest.raises(TaskNotFoundError):
            task_manager.retry("missing-task", _make_execution_request())


# ---------------------------------------------------------------------
# pause() / resume()
# ---------------------------------------------------------------------


class TestPauseResume:
    def test_pause_running_task(
        self,
        task_manager: TaskManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("task.paused", subscriber)

        request = TaskRequest(capability_id="capability.echo")
        task = task_manager.create(request)
        task.status = TaskStatus.RUNNING

        result = task_manager.pause(task.id)

        assert result.status is TaskStatus.PAUSED
        assert len(subscriber.received) == 1
        assert isinstance(subscriber.received[0], TaskPausedEvent)

    def test_pause_raises_when_not_running(
        self,
        task_manager: TaskManager,
    ) -> None:
        request = TaskRequest(capability_id="capability.echo")
        task = task_manager.create(request)

        with pytest.raises(TaskNotRunningError):
            task_manager.pause(task.id)

    def test_pause_raises_task_not_found(
        self,
        task_manager: TaskManager,
    ) -> None:
        with pytest.raises(TaskNotFoundError):
            task_manager.pause("missing-task")

    def test_resume_paused_task(
        self,
        task_manager: TaskManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("task.resumed", subscriber)

        request = TaskRequest(capability_id="capability.echo")
        task = task_manager.create(request)
        task.status = TaskStatus.PAUSED

        result = task_manager.resume(task.id)

        assert result.status is TaskStatus.RUNNING
        assert len(subscriber.received) == 1
        assert isinstance(subscriber.received[0], TaskResumedEvent)

    def test_resume_raises_when_not_paused(
        self,
        task_manager: TaskManager,
    ) -> None:
        request = TaskRequest(capability_id="capability.echo")
        task = task_manager.create(request)

        with pytest.raises(TaskPausedError):
            task_manager.resume(task.id)


# ---------------------------------------------------------------------
# cancel()
# ---------------------------------------------------------------------


class TestCancel:
    def test_cancel_pending_task(
        self,
        task_manager: TaskManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("task.cancelled", subscriber)

        request = TaskRequest(capability_id="capability.echo")
        task = task_manager.create(request)

        result = task_manager.cancel(task.id)

        assert result.status is TaskStatus.CANCELLED
        assert result.completed_at is not None
        assert len(subscriber.received) == 1
        assert isinstance(subscriber.received[0], TaskCancelledEvent)

    def test_cancel_running_task(
        self,
        task_manager: TaskManager,
    ) -> None:
        request = TaskRequest(capability_id="capability.echo")
        task = task_manager.create(request)
        task.status = TaskStatus.RUNNING

        result = task_manager.cancel(task.id)

        assert result.status is TaskStatus.CANCELLED

    def test_cannot_cancel_completed_task(
        self,
        task_manager: TaskManager,
    ) -> None:
        request = TaskRequest(capability_id="capability.echo")
        task = task_manager.create(request)
        task.status = TaskStatus.COMPLETED

        with pytest.raises(TaskAlreadyCompletedError):
            task_manager.cancel(task.id)

    def test_cannot_cancel_already_cancelled_task(
        self,
        task_manager: TaskManager,
    ) -> None:
        request = TaskRequest(capability_id="capability.echo")
        task = task_manager.create(request)
        task.status = TaskStatus.CANCELLED

        with pytest.raises(TaskCancelledError):
            task_manager.cancel(task.id)

    def test_cancel_raises_task_not_found(
        self,
        task_manager: TaskManager,
    ) -> None:
        with pytest.raises(TaskNotFoundError):
            task_manager.cancel("missing-task")
