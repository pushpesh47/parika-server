"""
PARIKA Workflow Execution Status

Defines the execution states of Execution instances managed by the
WorkflowEngine.

The execution status describes the current execution state of a workflow
execution. It is descriptive only and does not define or enforce execution
transitions such as starting, pausing, resuming, waiting, completion,
failure, or cancellation.

Execution lifecycle orchestration is managed internally by WorkflowEngine.
"""

from __future__ import annotations

from enum import StrEnum


class ExecutionStatus(StrEnum):
    """
    Execution state of a workflow execution.

    The execution status represents the current execution state of an
    Execution. It is descriptive only and carries no business logic.
    """

    PENDING = "pending"
    """The execution has been created but has not yet started."""

    RUNNING = "running"
    """The execution is currently in progress."""

    WAITING = "waiting"
    """The execution is waiting for an external dependency or event."""

    PAUSED = "paused"
    """The execution has been intentionally paused."""

    COMPLETED = "completed"
    """The execution completed successfully."""

    FAILED = "failed"
    """The execution terminated due to an unrecoverable error."""

    CANCELLED = "cancelled"
    """The execution was intentionally terminated before completion."""