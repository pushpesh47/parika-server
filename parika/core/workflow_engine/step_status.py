"""
PARIKA Step Status

Defines the execution states of Step instances executed by the
WorkflowEngine.

The step status describes the current execution state of an individual
Step within an Execution. It is descriptive only and does not define
or enforce execution transitions such as starting, completion,
failure, or skipping.

Step lifecycle orchestration is managed internally by WorkflowEngine.
"""

from __future__ import annotations

from enum import StrEnum


class StepStatus(StrEnum):
    """
    Execution state of an individual Step.

    The step status represents the current execution state of a Step
    within an Execution. It is descriptive only and carries no
    business logic.
    """

    PENDING = "pending"
    """The step has not yet started execution."""

    RUNNING = "running"
    """The step is currently executing."""

    COMPLETED = "completed"
    """The step completed successfully."""

    FAILED = "failed"
    """The step terminated due to an unrecoverable error."""

    SKIPPED = "skipped"
    """The step was intentionally not executed."""