"""
PARIKA Task Events

Defines the immutable lifecycle events published by TaskManager.

Task lifecycle events notify the EventBus whenever the execution state
of a Task changes. Events provide an immutable event object that
references the associated runtime Task and carries no business logic.

Task lifecycle orchestration remains the responsibility of
TaskManager.
"""

from __future__ import annotations

from dataclasses import dataclass

from .task import Task


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class TaskEvent:
    """
    Base class for all Task lifecycle events.

    Every Task lifecycle event references the associated runtime Task.
    """

    task: Task
    """
    Runtime Task associated with the event.
    """


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class TaskCreatedEvent(TaskEvent):
    """
    Published after a Task has been created.
    """


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class TaskStartedEvent(TaskEvent):
    """
    Published when a Task starts execution.
    """


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class TaskPausedEvent(TaskEvent):
    """
    Published when a Task is paused.
    """


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class TaskResumedEvent(TaskEvent):
    """
    Published when a paused Task resumes execution.
    """


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class TaskCompletedEvent(TaskEvent):
    """
    Published after a Task completes successfully.
    """


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class TaskCancelledEvent(TaskEvent):
    """
    Published after a Task is cancelled.
    """


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class TaskFailedEvent(TaskEvent):
    """
    Published after a Task fails.
    """