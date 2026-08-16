"""
PARIKA Scheduler

Provides the core component responsible for scheduling work to execute
at the appropriate time.

Scheduler maintains the authoritative runtime registry of
ScheduledJob instances, triggers one-time and recurring callbacks
using timers, tracks scheduling state, and publishes lifecycle events
through the EventBus.

Scheduler does not execute business logic and does not plan
workflows. The callback supplied to a ScheduledJob is treated as
opaque business logic owned entirely by the caller.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from threading import RLock, Timer
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger

from .events import (
    JobCancelledEvent,
    JobCompletedEvent,
    JobFailedEvent,
    JobScheduledEvent,
    JobTriggeredEvent,
)
from .exceptions import (
    InvalidScheduleError,
    JobAlreadyCancelledError,
    JobAlreadyFinishedError,
    JobNotFoundError,
    SchedulerError,
)
from .job_status import JobStatus
from .scheduled_job import ScheduledJob

JOB_SCHEDULED_EVENT = "scheduler.job.scheduled"
JOB_TRIGGERED_EVENT = "scheduler.job.triggered"
JOB_COMPLETED_EVENT = "scheduler.job.completed"
JOB_FAILED_EVENT = "scheduler.job.failed"
JOB_CANCELLED_EVENT = "scheduler.job.cancelled"


class Scheduler:
    """
    Schedules work to execute at the appropriate time.

    Scheduler owns the authoritative runtime registry of ScheduledJob
    instances. It supports delayed one-time execution and recurring
    execution, tracks job scheduling state, and publishes lifecycle
    events.

    Scheduler intentionally does not:

    - Execute business logic. Callbacks are opaque and owned by the
      caller.
    - Plan workflows.
    """

    def __init__(
        self,
        *,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        """
        Initialize the Scheduler.

        Args:
            event_bus:
                EventBus used to publish job lifecycle events.

            logger:
                PARIKA Logger component.
        """

        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

        self._lock = RLock()
        self._jobs: dict[str, ScheduledJob] = {}
        self._timers: dict[str, Timer] = {}

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    def schedule_once(
        self,
        callback: Callable[[], None],
        *,
        delay_seconds: float | None = None,
        run_at: datetime | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ScheduledJob:
        """
        Schedule a callback to trigger exactly once.

        Exactly one of `delay_seconds` or `run_at` must be supplied.

        Args:
            callback:
                Zero-argument callable to invoke when the job
                triggers.

            delay_seconds:
                Delay, in seconds, before the job triggers.

            run_at:
                Absolute timestamp at which the job should trigger.

            metadata:
                Optional implementation-neutral runtime metadata.

        Returns:
            The newly created ScheduledJob.

        Raises:
            InvalidScheduleError:
                If the schedule request is invalid.
        """

        run_at = self._resolve_run_at(
            delay_seconds=delay_seconds,
            run_at=run_at,
        )

        return self._create_job(
            callback,
            run_at=run_at,
            interval_seconds=None,
            metadata=metadata,
        )

    def schedule_interval(
        self,
        callback: Callable[[], None],
        *,
        interval_seconds: float,
        start_delay_seconds: float = 0.0,
        metadata: Mapping[str, Any] | None = None,
    ) -> ScheduledJob:
        """
        Schedule a callback to trigger repeatedly on a fixed interval.

        Args:
            callback:
                Zero-argument callable to invoke on every trigger.

            interval_seconds:
                Interval, in seconds, between triggers. Must be
                greater than zero.

            start_delay_seconds:
                Delay, in seconds, before the first trigger. Defaults
                to firing immediately.

            metadata:
                Optional implementation-neutral runtime metadata.

        Returns:
            The newly created ScheduledJob.

        Raises:
            InvalidScheduleError:
                If the schedule request is invalid.
        """

        if interval_seconds <= 0:
            raise InvalidScheduleError(
                "interval_seconds must be greater than zero."
            )

        if start_delay_seconds < 0:
            raise InvalidScheduleError(
                "start_delay_seconds must not be negative."
            )

        run_at = datetime.now(UTC) + timedelta(
            seconds=start_delay_seconds,
        )

        return self._create_job(
            callback,
            run_at=run_at,
            interval_seconds=interval_seconds,
            metadata=metadata,
        )

    def cancel(self, job_id: str) -> ScheduledJob:
        """
        Cancel a ScheduledJob.

        Args:
            job_id:
                Identifier of the job to cancel.

        Returns:
            The cancelled ScheduledJob.

        Raises:
            JobNotFoundError:
                If the job is not registered.

            JobAlreadyCancelledError:
                If the job has already been cancelled.

            JobAlreadyFinishedError:
                If the job is a one-time job that has already run to
                completion or failure, or if the job's callback is
                currently executing (`JobStatus.RUNNING`) and it is
                therefore already too late to prevent it from running.

        Notes:
            A job whose `Timer` has already fired is briefly
            `JobStatus.RUNNING` (see `_trigger()`) while its callback
            executes, outside of `_lock`. `cancel()` rejects a
            `RUNNING` job rather than silently overwriting its status
            to `CANCELLED`, which would otherwise misrepresent a job
            whose callback cannot, in fact, be prevented from running
            (or from having already run) -- see `_trigger()`'s own
            docstring for the full race-condition rationale.
        """

        with self._lock:
            job = self._require_job(job_id)

            if job.status is JobStatus.CANCELLED:
                raise JobAlreadyCancelledError(
                    f"Job '{job_id}' is already cancelled."
                )

            if job.status is JobStatus.RUNNING:
                raise JobAlreadyFinishedError(
                    f"Job '{job_id}' is currently running and it is "
                    "too late to cancel it."
                )

            if (
                job.interval_seconds is None
                and job.status in (JobStatus.COMPLETED, JobStatus.FAILED)
            ):
                raise JobAlreadyFinishedError(
                    f"Job '{job_id}' has already finished."
                )

            job.status = JobStatus.CANCELLED

            timer = self._timers.pop(job_id, None)

            if timer is not None:
                timer.cancel()

            event = JobCancelledEvent(job=job)

        self._event_bus.publish(JOB_CANCELLED_EVENT, event)

        self._logger.debug(
            "Cancelled job '%s'.",
            job_id,
        )

        return job

    def shutdown(self) -> None:
        """
        Cancel every currently scheduled job.

        Intended to be invoked during application shutdown to release
        all pending timers. A job whose callback has already started
        executing (`JobStatus.RUNNING`) at the moment `shutdown()`
        reaches it cannot be cancelled (see `cancel()`'s notes); it is
        left to run to completion/failure rather than being
        misrepresented as cancelled.
        """

        with self._lock:
            scheduled_job_ids = [
                job.id
                for job in self._jobs.values()
                if job.status is JobStatus.SCHEDULED
            ]

        for job_id in scheduled_job_ids:
            try:
                self.cancel(job_id)

            except SchedulerError:
                continue

        self._logger.debug("Scheduler shutdown complete.")

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------

    def get(self, job_id: str) -> ScheduledJob:
        """
        Retrieve a registered ScheduledJob.

        Raises:
            JobNotFoundError:
                If the job is not registered.
        """

        with self._lock:
            return self._require_job(job_id)

    def contains(self, job_id: str) -> bool:
        """
        Determine whether a ScheduledJob is registered.
        """

        with self._lock:
            return job_id in self._jobs

    def get_all(self) -> Mapping[str, ScheduledJob]:
        """
        Return all registered ScheduledJob instances.
        """

        with self._lock:
            return MappingProxyType(dict(self._jobs))

    def count(self) -> int:
        """
        Return the number of registered ScheduledJob instances.
        """

        with self._lock:
            return len(self._jobs)

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _resolve_run_at(
        self,
        *,
        delay_seconds: float | None,
        run_at: datetime | None,
    ) -> datetime:
        """
        Resolve the absolute trigger timestamp for a one-time job.

        Raises:
            InvalidScheduleError:
                If neither or both of delay_seconds/run_at are
                supplied, or if the supplied value is invalid.
        """

        if (delay_seconds is None) == (run_at is None):
            raise InvalidScheduleError(
                "Exactly one of 'delay_seconds' or 'run_at' must be "
                "supplied."
            )

        if delay_seconds is not None:

            if delay_seconds < 0:
                raise InvalidScheduleError(
                    "delay_seconds must not be negative."
                )

            return datetime.now(UTC) + timedelta(seconds=delay_seconds)

        assert run_at is not None
        return run_at

    def _create_job(
        self,
        callback: Callable[[], None],
        *,
        run_at: datetime,
        interval_seconds: float | None,
        metadata: Mapping[str, Any] | None,
    ) -> ScheduledJob:
        """
        Create, register, and arm a new ScheduledJob.

        Raises:
            InvalidScheduleError:
                If the supplied callback is not callable.
        """

        if not callable(callback):
            raise InvalidScheduleError(
                "callback must be callable."
            )

        with self._lock:
            job = ScheduledJob(
                id=uuid4().hex,
                status=JobStatus.SCHEDULED,
                callback=callback,
                run_at=run_at,
                interval_seconds=interval_seconds,
                metadata=dict(metadata or {}),
            )

            self._jobs[job.id] = job

            self._arm_timer(job)

            event = JobScheduledEvent(job=job)

        self._event_bus.publish(JOB_SCHEDULED_EVENT, event)

        self._logger.debug(
            "Scheduled job '%s' (run_at=%s, interval=%s).",
            job.id,
            job.run_at.isoformat(),
            job.interval_seconds,
        )

        return job

    def _arm_timer(self, job: ScheduledJob) -> None:
        """
        Create and start the underlying Timer for a job.

        Notes:
            This helper assumes the caller already holds the registry
            lock.
        """

        delay_seconds = max(
            0.0,
            (job.run_at - datetime.now(UTC)).total_seconds(),
        )

        timer = Timer(delay_seconds, self._trigger, args=[job.id])
        timer.daemon = True

        self._timers[job.id] = timer

        timer.start()

    def _trigger(self, job_id: str) -> None:
        """
        Invoke a job's callback and advance its scheduling state.

        Invoked from the Timer's background thread.

        Notes:
            The initial `JobStatus.CANCELLED` check and the transition
            to `JobStatus.RUNNING` happen atomically under `_lock`, but
            the callback itself is deliberately invoked *outside*
            `_lock` (an arbitrary, potentially slow caller-supplied
            callback must never hold up every other Scheduler
            operation for its own duration). This means a concurrent
            `cancel(job_id)` call can still be invoked by another
            thread after this method has already committed to
            `RUNNING` -- at that point the callback cannot be
            prevented from running (`Timer.cancel()` only prevents
            execution when called before the timer's delay elapses;
            once elapsed, the underlying Python `threading.Timer`
            provides no mechanism to interrupt an in-flight callback).
            `cancel()` accounts for this by rejecting a `RUNNING` job
            (`JobAlreadyFinishedError`) instead of overwriting its
            status to `CANCELLED`, which would otherwise misrepresent
            a callback that is either already executing or has
            already run.
        """

        with self._lock:
            job = self._jobs.get(job_id)

            if job is None or job.status is JobStatus.CANCELLED:
                return

            job.status = JobStatus.RUNNING

            triggered_event = JobTriggeredEvent(job=job)

        self._event_bus.publish(JOB_TRIGGERED_EVENT, triggered_event)

        try:
            job.callback()

        except Exception as ex:
            with self._lock:
                job.failure = ex
                job.status = JobStatus.FAILED
                self._timers.pop(job_id, None)

                failed_event = JobFailedEvent(job=job)

            self._event_bus.publish(JOB_FAILED_EVENT, failed_event)

            self._logger.exception(
                "Job '%s' callback raised an exception.",
                job_id,
            )
            return

        with self._lock:
            job.trigger_count += 1
            job.last_triggered_at = datetime.now(UTC)

            if job.status is JobStatus.CANCELLED:
                return

            if job.interval_seconds is not None:
                job.status = JobStatus.SCHEDULED
                job.run_at = datetime.now(UTC) + timedelta(
                    seconds=job.interval_seconds,
                )
                self._arm_timer(job)
            else:
                job.status = JobStatus.COMPLETED
                self._timers.pop(job_id, None)

            completed_event = JobCompletedEvent(job=job)

        self._event_bus.publish(JOB_COMPLETED_EVENT, completed_event)

        self._logger.debug(
            "Job '%s' triggered successfully.",
            job_id,
        )

    def _require_job(self, job_id: str) -> ScheduledJob:
        """
        Retrieve a registered ScheduledJob.

        Raises:
            JobNotFoundError:
                If the job is not registered.

        Notes:
            This helper assumes the caller already holds the registry
            lock.
        """

        try:
            return self._jobs[job_id]

        except KeyError as ex:
            raise JobNotFoundError(
                f"Job '{job_id}' was not found."
            ) from ex
