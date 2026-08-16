"""
PARIKA Scheduler Events

Defines the immutable lifecycle events published by Scheduler.

Scheduled job lifecycle events notify the EventBus whenever the
scheduling state of a ScheduledJob changes. Events provide an
immutable event object that references the associated runtime
ScheduledJob and carry no business logic.

Scheduled job lifecycle orchestration remains the responsibility of
Scheduler.
"""

from __future__ import annotations

from dataclasses import dataclass

from .scheduled_job import ScheduledJob


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class JobEvent:
    """
    Base class for all ScheduledJob lifecycle events.

    Every ScheduledJob lifecycle event references the associated
    runtime ScheduledJob.
    """

    job: ScheduledJob
    """
    Runtime ScheduledJob associated with the event.
    """


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class JobScheduledEvent(JobEvent):
    """
    Published after a job has been scheduled.
    """


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class JobTriggeredEvent(JobEvent):
    """
    Published when a job's callback begins executing.
    """


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class JobCompletedEvent(JobEvent):
    """
    Published after a job's callback completes successfully.
    """


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class JobFailedEvent(JobEvent):
    """
    Published after a job's callback raises an unhandled exception.
    """


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class JobCancelledEvent(JobEvent):
    """
    Published after a job has been cancelled.
    """
