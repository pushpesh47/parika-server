"""
PARIKA Task Manager

Provides the core component responsible for creating, executing,
tracking, and managing the runtime lifecycle of Task instances.

TaskManager maintains the authoritative runtime registry of Tasks,
coordinates Task lifecycle transitions, delegates capability execution
to CapabilityExecutor, and publishes Task lifecycle events through the
EventBus.

TaskManager does not build execution plans, resolve capabilities,
build capability execution requests, select execution backends, or
execute capabilities, tools, or providers directly. Backend execution
results are treated as opaque runtime objects and are never
interpreted or normalized by TaskManager.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from threading import RLock
from types import MappingProxyType
from uuid import uuid4

from parika.core.capability_executor.capability_executor import (
    CapabilityExecutor,
)
from parika.core.capability_executor.request import (
    CapabilityExecutionRequest,
)
from parika.core.capability_executor.response import (
    CapabilityExecutionResponse,
)
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger

from .events import (
    TaskCancelledEvent,
    TaskCompletedEvent,
    TaskCreatedEvent,
    TaskFailedEvent,
    TaskPausedEvent,
    TaskResumedEvent,
    TaskStartedEvent,
)
from .exceptions import (
    InvalidTaskRequestError,
    TaskAlreadyCompletedError,
    TaskAlreadyRunningError,
    TaskCancelledError,
    TaskExecutionError,
    TaskNotFoundError,
    TaskNotRunningError,
    TaskPausedError,
)
from .request import TaskRequest
from .response import TaskResponse
from .task import Task
from .task_status import TaskStatus

TASK_CREATED_EVENT = "task.created"
TASK_STARTED_EVENT = "task.started"
TASK_PAUSED_EVENT = "task.paused"
TASK_RESUMED_EVENT = "task.resumed"
TASK_COMPLETED_EVENT = "task.completed"
TASK_CANCELLED_EVENT = "task.cancelled"
TASK_FAILED_EVENT = "task.failed"


class TaskManager:
    """
    Creates, executes, tracks, and manages the lifecycle of Tasks.

    TaskManager owns the authoritative runtime registry of Task
    instances. It creates Tasks from immutable TaskRequest objects,
    coordinates their execution by delegating to CapabilityExecutor,
    tracks lifecycle transitions, and publishes Task lifecycle events.

    TaskManager intentionally does not:

    - Build execution plans.
    - Resolve capabilities.
    - Build capability execution requests.
    - Select execution backends.
    - Execute capabilities, tools, or providers directly.
    - Interpret or normalize backend execution results.
    - Schedule execution.
    """

    def __init__(
        self,
        *,
        event_bus: EventBus,
        logger: Logger,
        capability_executor: CapabilityExecutor,
    ) -> None:
        """
        Initialize the TaskManager.

        Args:
            event_bus:
                EventBus used to publish Task lifecycle events.

            logger:
                PARIKA Logger component.

            capability_executor:
                CapabilityExecutor used to execute resolved
                capabilities on behalf of Tasks.
        """

        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

        self._capability_executor = capability_executor

        self._lock = RLock()
        self._tasks: dict[str, Task] = {}

    # ------------------------------------------------------------------
    # Task Registry
    # ------------------------------------------------------------------

    def create(
        self,
        request: TaskRequest,
        *,
        execution_id: str | None = None,
        step_id: str | None = None,
        parent_task_id: str | None = None,
    ) -> Task:
        """
        Create a new runtime Task.

        Args:
            request:
                Immutable TaskRequest describing the Capability to
                execute.

            execution_id:
                Optional identifier of the originating Workflow
                Execution.

            step_id:
                Optional identifier of the originating Workflow Step.

            parent_task_id:
                Optional identifier of the parent Task for
                hierarchical execution.

        Returns:
            The newly created Task in PENDING status.

        Raises:
            InvalidTaskRequestError:
                If the supplied object is not a TaskRequest.
        """

        if not isinstance(request, TaskRequest):
            raise InvalidTaskRequestError(
                "Expected a TaskRequest instance."
            )

        with self._lock:
            task = Task(
                id=uuid4().hex,
                status=TaskStatus.PENDING,
                request=request,
                execution_id=execution_id,
                step_id=step_id,
                parent_task_id=parent_task_id,
            )

            self._tasks[task.id] = task

            event = TaskCreatedEvent(task=task)

        self._event_bus.publish(TASK_CREATED_EVENT, event)

        self._logger.debug(
            "Created task '%s' for capability '%s'.",
            task.id,
            request.capability_id,
        )

        return task

    def get(self, task_id: str) -> Task:
        """
        Retrieve a registered Task.

        Args:
            task_id:
                Identifier of the Task.

        Returns:
            The registered Task.

        Raises:
            TaskNotFoundError:
                If the Task is not registered.
        """

        with self._lock:
            return self._require_task(task_id)

    def contains(self, task_id: str) -> bool:
        """
        Determine whether a Task is registered.

        Args:
            task_id:
                Identifier of the Task.

        Returns:
            True if the Task is registered; otherwise False.
        """

        with self._lock:
            return task_id in self._tasks

    def get_all(self) -> Mapping[str, Task]:
        """
        Return all registered Tasks.

        Returns:
            Read-only mapping of Task identifiers to Task instances.
        """

        with self._lock:
            return MappingProxyType(dict(self._tasks))

    def count(self) -> int:
        """
        Return the number of registered Tasks.

        Returns:
            Total number of registered Task instances.
        """

        with self._lock:
            return len(self._tasks)

    def remove(self, task_id: str) -> None:
        """
        Remove a registered Task.

        Args:
            task_id:
                Identifier of the Task to remove.

        Raises:
            TaskNotFoundError:
                If the Task is not registered.
        """

        with self._lock:
            self._require_task(task_id)

            del self._tasks[task_id]

        self._logger.debug(
            "Removed task '%s'.",
            task_id,
        )

    # ------------------------------------------------------------------
    # Task Execution
    # ------------------------------------------------------------------

    def execute(
        self,
        task_id: str,
        execution_request: CapabilityExecutionRequest,
    ) -> Task:
        """
        Execute a Task.

        Execution is delegated entirely to CapabilityExecutor.
        TaskManager only coordinates the lifecycle transition and
        records the opaque execution result.

        Args:
            task_id:
                Identifier of the Task to execute.

            execution_request:
                Prepared CapabilityExecutionRequest supplied by the
                caller (e.g. Planner). TaskManager does not build or
                inspect this request.

        Returns:
            The Task after execution completes.

        Raises:
            TaskNotFoundError:
                If the Task is not registered.

            TaskAlreadyRunningError:
                If the Task is already running.

            TaskAlreadyCompletedError:
                If the Task has already completed successfully.

            TaskCancelledError:
                If the Task has been cancelled.

            TaskPausedError:
                If the Task is currently paused.

            TaskExecutionError:
                If execution fails.
        """

        with self._lock:
            task = self._require_task(task_id)
            self._guard_startable(task)

            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now(UTC)

            started_event = TaskStartedEvent(task=task)

        self._event_bus.publish(TASK_STARTED_EVENT, started_event)

        self._logger.debug(
            "Started task '%s' for capability '%s'.",
            task.id,
            task.request.capability_id,
        )

        try:
            execution_response = self._capability_executor.execute(
                execution_request,
                task_id=task.id,
            )

            with self._lock:
                self._complete(task, execution_response)

            return task

        except Exception as ex:

            with self._lock:
                self._fail(task, ex)

            raise TaskExecutionError(
                f"Task '{task_id}' execution failed."
            ) from ex

    def retry(
        self,
        task_id: str,
        execution_request: CapabilityExecutionRequest,
    ) -> Task:
        """
        Retry a previously failed Task.

        The Task is reset to PENDING, its retry count is incremented,
        and execution is re-attempted through the normal execution
        path.

        Args:
            task_id:
                Identifier of the Task to retry.

            execution_request:
                Prepared CapabilityExecutionRequest used for the retry
                attempt.

        Returns:
            The Task after the retry attempt completes.

        Raises:
            TaskNotFoundError:
                If the Task is not registered.

            TaskExecutionError:
                If the Task is not currently in a failed state, or if
                the retry attempt fails.
        """

        with self._lock:
            task = self._require_task(task_id)

            if task.status is not TaskStatus.FAILED:
                raise TaskExecutionError(
                    f"Task '{task_id}' is not in a failed state and "
                    "cannot be retried."
                )

            retry_count = task.metadata.get("retry_count", 0)
            task.metadata["retry_count"] = retry_count + 1

            task.status = TaskStatus.PENDING
            task.failure = None
            task.started_at = None
            task.completed_at = None

            self._logger.debug(
                "Retrying task '%s' (attempt %d).",
                task.id,
                task.metadata["retry_count"],
            )

        return self.execute(task_id, execution_request)

    # ------------------------------------------------------------------
    # Task Lifecycle
    # ------------------------------------------------------------------

    def pause(self, task_id: str) -> Task:
        """
        Pause a running Task.

        Args:
            task_id:
                Identifier of the Task to pause.

        Returns:
            The paused Task.

        Raises:
            TaskNotFoundError:
                If the Task is not registered.

            TaskNotRunningError:
                If the Task is not currently running.
        """

        with self._lock:
            task = self._require_task(task_id)

            if task.status is not TaskStatus.RUNNING:
                raise TaskNotRunningError(
                    f"Task '{task_id}' is not running."
                )

            task.status = TaskStatus.PAUSED

            event = TaskPausedEvent(task=task)

        self._event_bus.publish(TASK_PAUSED_EVENT, event)

        self._logger.debug(
            "Paused task '%s'.",
            task_id,
        )

        return task

    def resume(self, task_id: str) -> Task:
        """
        Resume a paused Task.

        Args:
            task_id:
                Identifier of the Task to resume.

        Returns:
            The resumed Task.

        Raises:
            TaskNotFoundError:
                If the Task is not registered.

            TaskPausedError:
                If the Task is not currently paused.
        """

        with self._lock:
            task = self._require_task(task_id)

            if task.status is not TaskStatus.PAUSED:
                raise TaskPausedError(
                    f"Task '{task_id}' is not paused."
                )

            task.status = TaskStatus.RUNNING

            event = TaskResumedEvent(task=task)

        self._event_bus.publish(TASK_RESUMED_EVENT, event)

        self._logger.debug(
            "Resumed task '%s'.",
            task_id,
        )

        return task

    def cancel(self, task_id: str) -> Task:
        """
        Cancel a Task.

        Args:
            task_id:
                Identifier of the Task to cancel.

        Returns:
            The cancelled Task.

        Raises:
            TaskNotFoundError:
                If the Task is not registered.

            TaskAlreadyCompletedError:
                If the Task has already completed successfully.

            TaskCancelledError:
                If the Task has already been cancelled.
        """

        with self._lock:
            task = self._require_task(task_id)

            if task.status is TaskStatus.COMPLETED:
                raise TaskAlreadyCompletedError(
                    f"Task '{task_id}' has already completed."
                )

            if task.status is TaskStatus.CANCELLED:
                raise TaskCancelledError(
                    f"Task '{task_id}' is already cancelled."
                )

            task.status = TaskStatus.CANCELLED
            task.completed_at = datetime.now(UTC)

            event = TaskCancelledEvent(task=task)

        self._event_bus.publish(TASK_CANCELLED_EVENT, event)

        self._logger.debug(
            "Cancelled task '%s'.",
            task_id,
        )

        return task

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _require_task(self, task_id: str) -> Task:
        """
        Retrieve a registered Task.

        Raises:
            TaskNotFoundError:
                If the Task is not registered.

        Notes:
            This helper assumes the caller already holds the registry
            lock.
        """

        try:
            return self._tasks[task_id]

        except KeyError as ex:
            raise TaskNotFoundError(
                f"Task '{task_id}' was not found."
            ) from ex

    def _guard_startable(self, task: Task) -> None:
        """
        Validate that a Task may transition into RUNNING.

        Raises:
            TaskAlreadyRunningError:
                If the Task is already running.

            TaskAlreadyCompletedError:
                If the Task has already completed successfully.

            TaskCancelledError:
                If the Task has been cancelled.

            TaskPausedError:
                If the Task is currently paused.

        Notes:
            This helper assumes the caller already holds the registry
            lock.
        """

        if task.status is TaskStatus.RUNNING:
            raise TaskAlreadyRunningError(
                f"Task '{task.id}' is already running."
            )

        if task.status is TaskStatus.COMPLETED:
            raise TaskAlreadyCompletedError(
                f"Task '{task.id}' has already completed."
            )

        if task.status is TaskStatus.CANCELLED:
            raise TaskCancelledError(
                f"Task '{task.id}' has been cancelled."
            )

        if task.status is TaskStatus.PAUSED:
            raise TaskPausedError(
                f"Task '{task.id}' is paused."
            )

    def _complete(
        self,
        task: Task,
        execution_response: CapabilityExecutionResponse,
    ) -> None:
        """
        Complete a Task successfully.

        The backend execution result carried by execution_response is
        treated as an opaque runtime object. Its contents are neither
        interpreted nor normalized; it is stored verbatim as a single
        output entry.

        Notes:
            This helper assumes the caller already holds the registry
            lock.
        """

        task.response = TaskResponse(
            outputs={"result": execution_response.backend_response},
            metadata=dict(execution_response.metadata),
            duration_seconds=execution_response.duration_seconds,
        )
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now(UTC)

        event = TaskCompletedEvent(task=task)

        self._event_bus.publish(TASK_COMPLETED_EVENT, event)

        self._logger.debug(
            "Completed task '%s'.",
            task.id,
        )

    def _fail(self, task: Task, failure: BaseException) -> None:
        """
        Fail a Task.

        Notes:
            This helper assumes the caller already holds the registry
            lock.
        """

        task.failure = failure
        task.status = TaskStatus.FAILED
        task.completed_at = datetime.now(UTC)

        event = TaskFailedEvent(task=task)

        self._event_bus.publish(TASK_FAILED_EVENT, event)

        self._logger.exception(
            "Task '%s' failed.",
            task.id,
        )
