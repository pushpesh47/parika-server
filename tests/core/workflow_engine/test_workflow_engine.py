"""
Unit tests for WorkflowEngine.

These tests exercise WorkflowEngine in isolation using the shared
`logger` / `event_bus` fixtures from `tests/conftest.py`.

IMPORTANT - reflects an incomplete implementation
---------------------------------------------------
As of this writing, `WorkflowEngine._create_execution()`
(workflow_engine.py) is an unconditional stub that always raises
`NotImplementedError`, and `WorkflowEngine._execute_step()` is an
identical unconditional stub. Because `execute()` calls
`_create_execution()` before doing anything else, the *only* public
entry point that would normally create an `Execution` can never
succeed - `execute()` always raises `NotImplementedError` for any
registered Workflow.

This means there is no working public path to get an `Execution` into
WorkflowEngine's active-execution registry. To test `pause()`,
`resume()`, `cancel()`, and the active-execution registry accessors
(all of which operate on *already active* Executions and are fully
implemented), these tests construct `Execution` instances directly and
seed them into `engine._executions` via the `_seed_active_execution`
helper below. This is deliberate whitebox test setup made necessary by
the current stub, not a preferred production pattern.

Tests for `_create_execution`, `_execute_step`, `_execute`,
`_advance_execution`, `_complete_execution`, `_fail_execution`, and
`_cleanup_execution` call these internal helpers directly for the same
reason: they are otherwise unreachable through the public API. This
still documents real, current behavior and will remain valuable once
the stubs are implemented.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from typing import Any

import pytest

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.workflow_engine.events import (
    WorkflowCancelledEvent,
    WorkflowCompletedEvent,
    WorkflowFailedEvent,
    WorkflowPausedEvent,
    WorkflowRegisteredEvent,
    WorkflowResumedEvent,
    WorkflowStartedEvent,
    WorkflowUnregisteredEvent,
)
from parika.core.workflow_engine.exceptions import (
    ExecutionNotFoundError,
    InvalidWorkflowDefinitionError,
    WorkflowAlreadyRegisteredError,
    WorkflowCancelledError,
    WorkflowNotFoundError,
    WorkflowNotRunningError,
    WorkflowPausedError,
)
from parika.core.workflow_engine.execution_status import ExecutionStatus
from parika.core.workflow_engine.workflow import Workflow
from parika.core.workflow_engine.workflow_engine import WorkflowEngine
from parika.core.workflow_engine.workflow_execution import Execution
from parika.core.workflow_engine.workflow_step import Step


class RecordingSubscriber:
    """Records every event payload it receives."""

    def __init__(self) -> None:
        self.received: list[Any] = []

    def __call__(self, payload: Any) -> None:
        self.received.append(payload)


@pytest.fixture
def engine(event_bus: EventBus, logger: Logger) -> WorkflowEngine:
    return WorkflowEngine(event_bus=event_bus, logger=logger)


def _make_step(
    step_id: str = "step-1",
    *,
    capability_id: str = "capability.echo",
    next_step_ids: tuple[str, ...] = (),
) -> Step:
    return Step(
        id=step_id,
        name=step_id,
        capability_id=capability_id,
        next_step_ids=next_step_ids,
    )


def _make_workflow(
    workflow_id: str = "workflow-1",
    *,
    steps: Mapping[str, Step] | None = None,
    entry_step_id: str = "step-1",
    version: str = "1.0.0",
) -> Workflow:
    if steps is None:
        steps = {"step-1": _make_step("step-1")}

    return Workflow(
        id=workflow_id,
        name=workflow_id,
        version=version,
        step_definitions=steps,
        entry_step_id=entry_step_id,
    )


def _make_execution(
    execution_id: str = "execution-1",
    *,
    workflow_id: str = "workflow-1",
    status: ExecutionStatus = ExecutionStatus.RUNNING,
    context_id: str = "context-1",
    current_step_id: str | None = "step-1",
) -> Execution:
    return Execution(
        id=execution_id,
        workflow_id=workflow_id,
        status=status,
        context_id=context_id,
        current_step_id=current_step_id,
        created_at=datetime.now(UTC),
    )


def _seed_active_execution(engine: WorkflowEngine, execution: Execution) -> Execution:
    """
    Insert an Execution directly into the engine's active registry.

    Necessary whitebox setup: `execute()` can never successfully
    create an Execution because `_create_execution()` is an
    unconditional `NotImplementedError` stub (see module docstring).
    """

    engine._executions[execution.id] = execution
    return execution


# ---------------------------------------------------------------------
# Workflow / Step value objects
# ---------------------------------------------------------------------


class TestWorkflowAndStep:
    def test_workflow_is_frozen(self) -> None:
        workflow = _make_workflow()

        with pytest.raises(FrozenInstanceError):
            workflow.name = "renamed"  # type: ignore[misc]

    def test_step_is_frozen(self) -> None:
        step = _make_step()

        with pytest.raises(FrozenInstanceError):
            step.name = "renamed"  # type: ignore[misc]

    def test_workflow_defaults(self) -> None:
        workflow = _make_workflow()

        assert workflow.description is None
        assert dict(workflow.metadata) == {}

    def test_step_defaults(self) -> None:
        step = _make_step()

        assert step.description is None
        assert dict(step.inputs) == {}
        assert dict(step.outputs) == {}
        assert step.next_step_ids == ()
        assert dict(step.metadata) == {}


# ---------------------------------------------------------------------
# register()
# ---------------------------------------------------------------------


class TestRegister:
    def test_registers_workflow(
        self,
        engine: WorkflowEngine,
    ) -> None:
        workflow = _make_workflow()

        engine.register(workflow)

        assert engine.contains(workflow.id)
        assert engine.get(workflow.id) is workflow
        assert engine.count() == 1

    def test_publishes_registered_event(
        self,
        engine: WorkflowEngine,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("workflow.registered", subscriber)

        workflow = _make_workflow()
        engine.register(workflow)

        assert len(subscriber.received) == 1
        event = subscriber.received[0]
        assert isinstance(event, WorkflowRegisteredEvent)
        assert event.workflow_id == workflow.id

    def test_rejects_duplicate_registration(
        self,
        engine: WorkflowEngine,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("workflow.registered", subscriber)

        workflow = _make_workflow()
        engine.register(workflow)

        duplicate = _make_workflow()
        with pytest.raises(WorkflowAlreadyRegisteredError):
            engine.register(duplicate)

        # No second event published, and the original definition is
        # left untouched in the registry.
        assert len(subscriber.received) == 1
        assert engine.get(workflow.id) is workflow
        assert engine.count() == 1

    def test_rejects_workflow_with_no_steps(
        self,
        engine: WorkflowEngine,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("workflow.registered", subscriber)

        workflow = _make_workflow(steps={}, entry_step_id="step-1")

        with pytest.raises(InvalidWorkflowDefinitionError):
            engine.register(workflow)

        assert engine.count() == 0
        assert len(subscriber.received) == 0

    def test_rejects_workflow_with_unknown_entry_step(
        self,
        engine: WorkflowEngine,
    ) -> None:
        workflow = _make_workflow(
            steps={"step-1": _make_step("step-1")},
            entry_step_id="missing-step",
        )

        with pytest.raises(InvalidWorkflowDefinitionError):
            engine.register(workflow)

        assert engine.count() == 0

    def test_rejects_workflow_with_unknown_next_step(
        self,
        engine: WorkflowEngine,
    ) -> None:
        steps = {
            "step-1": _make_step("step-1", next_step_ids=("missing-step",)),
        }
        workflow = _make_workflow(steps=steps, entry_step_id="step-1")

        with pytest.raises(InvalidWorkflowDefinitionError):
            engine.register(workflow)

        assert engine.count() == 0

    def test_accepts_workflow_with_valid_multi_step_chain(
        self,
        engine: WorkflowEngine,
    ) -> None:
        steps = {
            "step-1": _make_step("step-1", next_step_ids=("step-2",)),
            "step-2": _make_step("step-2"),
        }
        workflow = _make_workflow(steps=steps, entry_step_id="step-1")

        engine.register(workflow)

        assert engine.contains(workflow.id)

    def test_register_has_no_runtime_type_check(
        self,
        engine: WorkflowEngine,
    ) -> None:
        """
        BUG FOUND / documented current behavior: unlike TaskManager.create()
        (which raises a dedicated InvalidTaskRequestError for a non-TaskRequest
        argument), WorkflowEngine.register() performs no isinstance check on
        its `workflow` argument. Passing an object without a `.id` attribute
        crashes with a plain AttributeError instead of a WorkflowEngine-specific
        exception such as InvalidWorkflowDefinitionError. This test locks in
        that actual current behavior; it does not fix it.
        """

        with pytest.raises(AttributeError):
            engine.register(object())  # type: ignore[arg-type]


# ---------------------------------------------------------------------
# unregister()
# ---------------------------------------------------------------------


class TestUnregister:
    def test_unregisters_workflow(
        self,
        engine: WorkflowEngine,
    ) -> None:
        workflow = _make_workflow()
        engine.register(workflow)

        engine.unregister(workflow.id)

        assert not engine.contains(workflow.id)
        assert engine.count() == 0

    def test_publishes_unregistered_event(
        self,
        engine: WorkflowEngine,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("workflow.unregistered", subscriber)

        workflow = _make_workflow()
        engine.register(workflow)
        engine.unregister(workflow.id)

        assert len(subscriber.received) == 1
        event = subscriber.received[0]
        assert isinstance(event, WorkflowUnregisteredEvent)
        assert event.workflow_id == workflow.id

    def test_raises_when_missing(
        self,
        engine: WorkflowEngine,
    ) -> None:
        with pytest.raises(WorkflowNotFoundError):
            engine.unregister("missing-workflow")


# ---------------------------------------------------------------------
# get() / contains() / get_all() / count()
# ---------------------------------------------------------------------


class TestWorkflowRegistryQueries:
    def test_get_raises_when_missing(
        self,
        engine: WorkflowEngine,
    ) -> None:
        with pytest.raises(WorkflowNotFoundError):
            engine.get("missing-workflow")

    def test_contains_reflects_registry_state(
        self,
        engine: WorkflowEngine,
    ) -> None:
        assert not engine.contains("missing-workflow")

        workflow = _make_workflow()
        engine.register(workflow)

        assert engine.contains(workflow.id)

    def test_get_all_and_count(
        self,
        engine: WorkflowEngine,
    ) -> None:
        assert engine.count() == 0

        first = _make_workflow("workflow-a")
        second = _make_workflow("workflow-b")
        engine.register(first)
        engine.register(second)

        all_workflows = engine.get_all()

        assert engine.count() == 2
        assert set(all_workflows) == {first.id, second.id}

    def test_get_all_is_read_only(
        self,
        engine: WorkflowEngine,
    ) -> None:
        engine.register(_make_workflow())

        all_workflows = engine.get_all()

        with pytest.raises(TypeError):
            all_workflows["new-key"] = object()  # type: ignore[index]

    def test_get_all_is_a_live_view_not_a_snapshot(
        self,
        engine: WorkflowEngine,
    ) -> None:
        """
        Documents actual current behavior: `get_all()` returns
        `MappingProxyType(self._workflows)`, a read-only *view* over
        the live internal dict (unlike TaskManager.get_all(), which
        wraps a defensive copy: `MappingProxyType(dict(self._tasks))`).
        Registrations made after calling `get_all()` are therefore
        visible through the previously returned mapping. This is a
        design difference worth flagging, not a bug being fixed here.
        """

        first = _make_workflow("workflow-a")
        engine.register(first)

        snapshot = engine.get_all()
        assert set(snapshot) == {"workflow-a"}

        second = _make_workflow("workflow-b")
        engine.register(second)

        assert set(snapshot) == {"workflow-a", "workflow-b"}


# ---------------------------------------------------------------------
# execute()
# ---------------------------------------------------------------------


class TestExecute:
    def test_raises_workflow_not_found(
        self,
        engine: WorkflowEngine,
    ) -> None:
        with pytest.raises(WorkflowNotFoundError):
            engine.execute("missing-workflow")

        assert engine.active_execution_count() == 0

    def test_raises_not_implemented_for_registered_workflow(
        self,
        engine: WorkflowEngine,
        event_bus: EventBus,
    ) -> None:
        """
        BUG FOUND / INCOMPLETE IMPLEMENTATION:
        `WorkflowEngine._create_execution()` (workflow_engine.py) is an
        unconditional `raise NotImplementedError` stub. `execute()` calls
        it immediately after resolving the Workflow, so executing *any*
        registered Workflow always raises `NotImplementedError` - there
        is currently no way to successfully start a workflow execution
        through the public API. This test locks in that current
        behavior rather than fixing the stub.
        """

        subscriber = RecordingSubscriber()
        event_bus.subscribe("workflow.started", subscriber)

        workflow = _make_workflow()
        engine.register(workflow)

        with pytest.raises(NotImplementedError):
            engine.execute(workflow.id)

        # The failure happens before the execution is registered or the
        # started event is published.
        assert engine.active_execution_count() == 0
        assert len(subscriber.received) == 0

    def test_accepts_optional_context_id_argument(
        self,
        engine: WorkflowEngine,
    ) -> None:
        workflow = _make_workflow()
        engine.register(workflow)

        with pytest.raises(NotImplementedError):
            engine.execute(workflow.id, context_id="context-1")


# ---------------------------------------------------------------------
# pause() / resume()
# ---------------------------------------------------------------------


class TestPauseResume:
    def test_pause_running_execution(
        self,
        engine: WorkflowEngine,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("workflow.paused", subscriber)

        execution = _seed_active_execution(
            engine, _make_execution(status=ExecutionStatus.RUNNING)
        )

        engine.pause(execution.id)

        assert execution.status is ExecutionStatus.PAUSED
        assert len(subscriber.received) == 1
        event = subscriber.received[0]
        assert isinstance(event, WorkflowPausedEvent)
        assert event.execution_id == execution.id
        assert event.workflow_id == execution.workflow_id

    def test_pause_raises_when_already_paused(
        self,
        engine: WorkflowEngine,
    ) -> None:
        execution = _seed_active_execution(
            engine, _make_execution(status=ExecutionStatus.PAUSED)
        )

        with pytest.raises(WorkflowPausedError):
            engine.pause(execution.id)

    def test_pause_raises_when_not_running(
        self,
        engine: WorkflowEngine,
    ) -> None:
        execution = _seed_active_execution(
            engine, _make_execution(status=ExecutionStatus.PENDING)
        )

        with pytest.raises(WorkflowNotRunningError):
            engine.pause(execution.id)

    def test_pause_raises_execution_not_found(
        self,
        engine: WorkflowEngine,
    ) -> None:
        with pytest.raises(ExecutionNotFoundError):
            engine.pause("missing-execution")

    def test_resume_sets_running_and_publishes_event(
        self,
        engine: WorkflowEngine,
        event_bus: EventBus,
    ) -> None:
        """
        BUG FOUND / INCOMPLETE IMPLEMENTATION:
        `resume()` transitions the Execution to RUNNING and publishes
        `workflow.resumed`, then calls `self._execute(execution)`. Because
        `_execute_step()` is also an unconditional `NotImplementedError`
        stub, and `_execute()` loops while status is RUNNING, any
        successful resume() call ultimately raises `NotImplementedError`
        once it reaches that inner loop - even though the state
        transition and event publication already happened. This test
        documents both halves of that current behavior.
        """

        subscriber = RecordingSubscriber()
        event_bus.subscribe("workflow.resumed", subscriber)

        execution = _seed_active_execution(
            engine, _make_execution(status=ExecutionStatus.PAUSED)
        )

        with pytest.raises(NotImplementedError):
            engine.resume(execution.id)

        assert execution.status is ExecutionStatus.RUNNING
        assert len(subscriber.received) == 1
        event = subscriber.received[0]
        assert isinstance(event, WorkflowResumedEvent)
        assert event.execution_id == execution.id

    def test_resume_raises_when_not_paused(
        self,
        engine: WorkflowEngine,
    ) -> None:
        execution = _seed_active_execution(
            engine, _make_execution(status=ExecutionStatus.RUNNING)
        )

        with pytest.raises(WorkflowPausedError):
            engine.resume(execution.id)

    def test_resume_raises_execution_not_found(
        self,
        engine: WorkflowEngine,
    ) -> None:
        with pytest.raises(ExecutionNotFoundError):
            engine.resume("missing-execution")


# ---------------------------------------------------------------------
# cancel()
# ---------------------------------------------------------------------


class TestCancel:
    def test_cancel_running_execution(
        self,
        engine: WorkflowEngine,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("workflow.cancelled", subscriber)

        execution = _seed_active_execution(
            engine, _make_execution(status=ExecutionStatus.RUNNING)
        )

        engine.cancel(execution.id)

        assert execution.status is ExecutionStatus.CANCELLED
        assert not engine.contains_active_execution(execution.id)
        assert len(subscriber.received) == 1
        event = subscriber.received[0]
        assert isinstance(event, WorkflowCancelledEvent)
        assert event.execution_id == execution.id

    def test_cancel_paused_execution(
        self,
        engine: WorkflowEngine,
    ) -> None:
        execution = _seed_active_execution(
            engine, _make_execution(status=ExecutionStatus.PAUSED)
        )

        engine.cancel(execution.id)

        assert execution.status is ExecutionStatus.CANCELLED

    def test_cancel_pending_execution(
        self,
        engine: WorkflowEngine,
    ) -> None:
        """
        Documents current behavior: unlike `pause()`, `cancel()` has no
        "must be running" guard - it only rejects an execution that is
        already CANCELLED. A PENDING execution can therefore be
        cancelled directly.
        """

        execution = _seed_active_execution(
            engine, _make_execution(status=ExecutionStatus.PENDING)
        )

        engine.cancel(execution.id)

        assert execution.status is ExecutionStatus.CANCELLED

    def test_cancel_raises_when_already_cancelled(
        self,
        engine: WorkflowEngine,
    ) -> None:
        execution = _seed_active_execution(
            engine, _make_execution(status=ExecutionStatus.CANCELLED)
        )

        with pytest.raises(WorkflowCancelledError):
            engine.cancel(execution.id)

    def test_cancel_raises_execution_not_found(
        self,
        engine: WorkflowEngine,
    ) -> None:
        with pytest.raises(ExecutionNotFoundError):
            engine.cancel("missing-execution")


# ---------------------------------------------------------------------
# Active Execution Registry
# ---------------------------------------------------------------------


class TestActiveExecutionRegistry:
    def test_contains_active_execution(
        self,
        engine: WorkflowEngine,
    ) -> None:
        assert not engine.contains_active_execution("missing-execution")

        execution = _seed_active_execution(engine, _make_execution())

        assert engine.contains_active_execution(execution.id)

    def test_get_active_execution_returns_registered_execution(
        self,
        engine: WorkflowEngine,
    ) -> None:
        execution = _seed_active_execution(engine, _make_execution())

        assert engine.get_active_execution(execution.id) is execution

    def test_get_active_execution_raises_when_missing(
        self,
        engine: WorkflowEngine,
    ) -> None:
        with pytest.raises(ExecutionNotFoundError):
            engine.get_active_execution("missing-execution")

    def test_get_active_executions_and_count(
        self,
        engine: WorkflowEngine,
    ) -> None:
        assert engine.active_execution_count() == 0

        first = _seed_active_execution(engine, _make_execution("execution-a"))
        second = _seed_active_execution(engine, _make_execution("execution-b"))

        all_executions = engine.get_active_executions()

        assert engine.active_execution_count() == 2
        assert set(all_executions) == {first.id, second.id}

    def test_get_active_executions_is_read_only(
        self,
        engine: WorkflowEngine,
    ) -> None:
        _seed_active_execution(engine, _make_execution())

        all_executions = engine.get_active_executions()

        with pytest.raises(TypeError):
            all_executions["new-key"] = object()  # type: ignore[index]


# ---------------------------------------------------------------------
# Internal helpers - _create_execution() / _execute_step()
#
# Both are unconditional NotImplementedError stubs (see module
# docstring). Exercised directly since they are unreachable through
# any successful public call path.
# ---------------------------------------------------------------------


class TestCreateExecutionStub:
    def test_always_raises_not_implemented(
        self,
        engine: WorkflowEngine,
    ) -> None:
        workflow = _make_workflow()

        with pytest.raises(NotImplementedError):
            engine._create_execution(workflow, context_id=None)

    def test_always_raises_not_implemented_with_context_id(
        self,
        engine: WorkflowEngine,
    ) -> None:
        workflow = _make_workflow()

        with pytest.raises(NotImplementedError):
            engine._create_execution(workflow, context_id="context-1")


class TestExecuteStepStub:
    def test_always_raises_not_implemented(
        self,
        engine: WorkflowEngine,
    ) -> None:
        execution = _make_execution()

        with pytest.raises(NotImplementedError):
            engine._execute_step(execution)


# ---------------------------------------------------------------------
# Internal helper - _execute()
# ---------------------------------------------------------------------


class TestExecuteLoop:
    def test_no_op_when_not_running(
        self,
        engine: WorkflowEngine,
    ) -> None:
        execution = _make_execution(status=ExecutionStatus.PAUSED)

        # Must not raise: the loop condition is false immediately, so
        # `_execute_step()` (the NotImplementedError stub) is never
        # invoked.
        engine._execute(execution)

        assert execution.status is ExecutionStatus.PAUSED

    def test_delegates_to_execute_step_when_running(
        self,
        engine: WorkflowEngine,
    ) -> None:
        execution = _make_execution(status=ExecutionStatus.RUNNING)

        with pytest.raises(NotImplementedError):
            engine._execute(execution)


# ---------------------------------------------------------------------
# Internal helper - _advance_execution()
# ---------------------------------------------------------------------


class TestAdvanceExecution:
    def test_advances_to_next_step(
        self,
        engine: WorkflowEngine,
    ) -> None:
        execution = _seed_active_execution(
            engine, _make_execution(current_step_id="step-1")
        )

        engine._advance_execution(execution, "step-2")

        assert execution.current_step_id == "step-2"
        assert execution.status is ExecutionStatus.RUNNING

    def test_completes_execution_when_next_step_is_none(
        self,
        engine: WorkflowEngine,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("workflow.completed", subscriber)

        execution = _seed_active_execution(engine, _make_execution())

        engine._advance_execution(execution, None)

        assert execution.status is ExecutionStatus.COMPLETED
        assert not engine.contains_active_execution(execution.id)
        assert len(subscriber.received) == 1
        assert isinstance(subscriber.received[0], WorkflowCompletedEvent)


# ---------------------------------------------------------------------
# Internal helper - _complete_execution()
# ---------------------------------------------------------------------


class TestCompleteExecution:
    def test_completes_and_cleans_up(
        self,
        engine: WorkflowEngine,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("workflow.completed", subscriber)

        execution = _seed_active_execution(engine, _make_execution())

        engine._complete_execution(execution)

        assert execution.status is ExecutionStatus.COMPLETED
        assert not engine.contains_active_execution(execution.id)
        assert len(subscriber.received) == 1
        event = subscriber.received[0]
        assert isinstance(event, WorkflowCompletedEvent)
        assert event.execution_id == execution.id
        assert event.workflow_id == execution.workflow_id


# ---------------------------------------------------------------------
# Internal helper - _fail_execution()
# ---------------------------------------------------------------------


class TestFailExecution:
    def test_fails_and_cleans_up(
        self,
        engine: WorkflowEngine,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("workflow.failed", subscriber)

        execution = _seed_active_execution(engine, _make_execution())

        engine._fail_execution(execution, "boom")

        assert execution.status is ExecutionStatus.FAILED
        assert execution.failure_reason == "boom"
        assert not engine.contains_active_execution(execution.id)
        assert len(subscriber.received) == 1
        event = subscriber.received[0]
        assert isinstance(event, WorkflowFailedEvent)
        assert event.execution_id == execution.id
        assert event.failure_reason == "boom"


# ---------------------------------------------------------------------
# Internal helper - _cleanup_execution()
# ---------------------------------------------------------------------


class TestCleanupExecution:
    def test_removes_active_execution(
        self,
        engine: WorkflowEngine,
    ) -> None:
        execution = _seed_active_execution(engine, _make_execution())

        engine._cleanup_execution(execution)

        assert not engine.contains_active_execution(execution.id)

    def test_is_safe_when_execution_not_active(
        self,
        engine: WorkflowEngine,
    ) -> None:
        execution = _make_execution()

        # Must not raise even though the execution was never seeded
        # into the active registry.
        engine._cleanup_execution(execution)

        assert not engine.contains_active_execution(execution.id)
