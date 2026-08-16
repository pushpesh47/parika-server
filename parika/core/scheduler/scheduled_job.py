"""
PARIKA Scheduled Job

Defines the mutable runtime ScheduledJob managed by Scheduler.

A ScheduledJob represents a single unit of work registered with
Scheduler to be triggered once, after a delay, or repeatedly on a
fixed interval. It owns only the scheduling state required by
Scheduler and contains no business logic. The callback supplied by the
caller owns all business logic executed when the job triggers.
"""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .job_status import JobStatus


@dataclass(slots=True, kw_only=True)
class ScheduledJob:
    """
    Mutable runtime ScheduledJob.

    A ScheduledJob represents the runtime scheduling state of a single
    callback registered with Scheduler. It is created, managed, and
    destroyed exclusively by Scheduler and contains no business logic.
    """

    id: str
    """
    Unique runtime identifier of the ScheduledJob.
    """

    status: JobStatus
    """
    Current scheduling state of the job.
    """

    callback: Callable[[], None]
    """
    Zero-argument callable invoked when the job triggers.

    Scheduler treats this callable as opaque business logic supplied
    by the caller.
    """

    run_at: datetime
    """
    Timestamp at which the job is next scheduled to trigger.
    """

    interval_seconds: float | None = None
    """
    Recurrence interval in seconds.

    None indicates a one-time job.
    """

    trigger_count: int = 0
    """
    Number of times the job has triggered.
    """

    created_at: datetime = field(
        default_factory=lambda: datetime.now(UTC),
    )
    """
    Timestamp when the job was scheduled.
    """

    last_triggered_at: datetime | None = None
    """
    Timestamp when the job last triggered.
    """

    failure: BaseException | None = None
    """
    Exception raised by the callback during the most recent trigger,
    if any.
    """

    metadata: MutableMapping[str, Any] = field(
        default_factory=dict,
    )
    """
    Mutable implementation-neutral runtime metadata.

    Scheduler does not assign semantics to these values.
    """
