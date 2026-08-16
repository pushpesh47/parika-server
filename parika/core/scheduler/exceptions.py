"""
PARIKA Scheduler Exceptions

Defines the exception hierarchy used by Scheduler.

These exceptions represent errors encountered while scheduling,
retrieving, cancelling, and triggering runtime ScheduledJob instances.

All Scheduler-specific exceptions derive from SchedulerError.
"""

from __future__ import annotations


class SchedulerError(Exception):
    """
    Base exception for all Scheduler errors.
    """


class JobNotFoundError(SchedulerError):
    """
    Raised when a requested ScheduledJob cannot be found.
    """


class InvalidScheduleError(SchedulerError):
    """
    Raised when a schedule request is structurally or semantically
    invalid.
    """


class JobAlreadyCancelledError(SchedulerError):
    """
    Raised when attempting to cancel a ScheduledJob that has already
    been cancelled.
    """


class JobAlreadyFinishedError(SchedulerError):
    """
    Raised when an operation cannot be performed because it is
    already too late for it to have any effect.

    Covers both:

    - A one-time (non-recurring) ScheduledJob that has already run to
      completion or failure.
    - A ScheduledJob whose callback is currently executing
      (`JobStatus.RUNNING`) at the moment `cancel()` is called --
      the callback cannot be prevented from running (or from having
      already run) once it has reached this state, so `cancel()`
      raises rather than misrepresenting the job as `CANCELLED`.
    """
