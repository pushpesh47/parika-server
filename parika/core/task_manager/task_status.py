"""
PARIKA Task Status

Defines the execution states of Task instances managed by the
TaskManager.

The task status describes the current execution state of an individual
Task during its runtime lifecycle. It is descriptive only and does not
define or enforce execution transitions such as creation, execution,
waiting, pausing, completion, failure, or cancellation.

Task lifecycle orchestration is managed internally by TaskManager.
"""

from __future__ import annotations

from enum import StrEnum


class TaskStatus(StrEnum):
    """
    Execution state of an individual Task.

    The task status represents the current execution state of a Task
    managed by TaskManager. It is descriptive only and carries no
    business logic.
    """

    PENDING = "pending"
    """The task has been created but has not yet started execution."""

    RUNNING = "running"
    """The task is currently executing."""

    WAITING = "waiting"
    """The task is temporarily waiting for an external dependency or event before execution can continue."""

    PAUSED = "paused"
    """The task execution has been intentionally paused."""

    COMPLETED = "completed"
    """The task completed successfully."""

    FAILED = "failed"
    """The task terminated due to an unrecoverable error."""

    CANCELLED = "cancelled"
    """The task execution was intentionally cancelled before completion."""