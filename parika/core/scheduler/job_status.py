"""
PARIKA Scheduled Job Status

Defines the execution states of ScheduledJob instances managed by the
Scheduler.

The job status describes the current state of an individual scheduled
job during its runtime lifecycle. It is descriptive only and does not
define or enforce state transitions.

Scheduled job lifecycle orchestration is managed internally by
Scheduler.
"""

from __future__ import annotations

from enum import StrEnum


class JobStatus(StrEnum):
    """
    Execution state of an individual ScheduledJob.

    The job status represents the current state of a job managed by
    Scheduler. It is descriptive only and carries no business logic.
    """

    SCHEDULED = "scheduled"
    """The job has been scheduled but has not yet triggered."""

    RUNNING = "running"
    """The job's callback is currently executing."""

    COMPLETED = "completed"
    """The job's callback completed successfully.

    For recurring jobs, this status is transient and is immediately
    followed by a new SCHEDULED state for the next occurrence.
    """

    FAILED = "failed"
    """The job's callback raised an unhandled exception."""

    CANCELLED = "cancelled"
    """The job was intentionally cancelled before triggering."""
