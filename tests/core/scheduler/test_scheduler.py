"""
Unit tests for Scheduler.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from parika.core.event_bus.event_bus import EventBus
from parika.core.scheduler.events import (
    JobCancelledEvent,
    JobCompletedEvent,
    JobFailedEvent,
    JobScheduledEvent,
    JobTriggeredEvent,
)
from parika.core.scheduler.exceptions import (
    InvalidScheduleError,
    JobAlreadyCancelledError,
    JobAlreadyFinishedError,
    JobNotFoundError,
)
from parika.core.scheduler.job_status import JobStatus
from parika.core.scheduler.scheduler import Scheduler

_POLL_TIMEOUT = 2.0
_POLL_INTERVAL = 0.01


class _FakeLogger:
    def get_logger(self, name: str) -> logging.Logger:
        return logging.getLogger(name)


class RecordingSubscriber:
    def __init__(self) -> None:
        self.received: list[Any] = []

    def __call__(self, payload: Any) -> None:
        self.received.append(payload)


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus(logger=_FakeLogger())  # type: ignore[arg-type]


@pytest.fixture
def scheduler(event_bus: EventBus) -> Scheduler:
    return Scheduler(event_bus=event_bus, logger=_FakeLogger())  # type: ignore[arg-type]


def _wait_until(predicate: Any, timeout: float = _POLL_TIMEOUT) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(_POLL_INTERVAL)
    raise AssertionError("Condition was not met within timeout.")


# ---------------------------------------------------------------------
# schedule_once()
# ---------------------------------------------------------------------


class TestScheduleOnce:
    def test_triggers_callback_after_delay(
        self,
        scheduler: Scheduler,
    ) -> None:
        calls: list[int] = []

        job = scheduler.schedule_once(
            lambda: calls.append(1),
            delay_seconds=0.01,
        )

        assert job.status is JobStatus.SCHEDULED

        _wait_until(lambda: len(calls) == 1)
        _wait_until(lambda: scheduler.get(job.id).status is JobStatus.COMPLETED)

        assert scheduler.get(job.id).trigger_count == 1

    def test_supports_absolute_run_at(
        self,
        scheduler: Scheduler,
    ) -> None:
        calls: list[int] = []
        run_at = datetime.now(UTC) + timedelta(milliseconds=10)

        scheduler.schedule_once(lambda: calls.append(1), run_at=run_at)

        _wait_until(lambda: len(calls) == 1)

    def test_rejects_both_delay_and_run_at(
        self,
        scheduler: Scheduler,
    ) -> None:
        with pytest.raises(InvalidScheduleError):
            scheduler.schedule_once(
                lambda: None,
                delay_seconds=1.0,
                run_at=datetime.now(UTC),
            )

    def test_rejects_neither_delay_nor_run_at(
        self,
        scheduler: Scheduler,
    ) -> None:
        with pytest.raises(InvalidScheduleError):
            scheduler.schedule_once(lambda: None)

    def test_rejects_negative_delay(
        self,
        scheduler: Scheduler,
    ) -> None:
        with pytest.raises(InvalidScheduleError):
            scheduler.schedule_once(lambda: None, delay_seconds=-1.0)

    def test_rejects_non_callable(
        self,
        scheduler: Scheduler,
    ) -> None:
        with pytest.raises(InvalidScheduleError):
            scheduler.schedule_once(
                "not-callable",  # type: ignore[arg-type]
                delay_seconds=0.01,
            )

    def test_publishes_scheduled_and_completed_events(
        self,
        scheduler: Scheduler,
        event_bus: EventBus,
    ) -> None:
        scheduled = RecordingSubscriber()
        triggered = RecordingSubscriber()
        completed = RecordingSubscriber()
        event_bus.subscribe("scheduler.job.scheduled", scheduled)
        event_bus.subscribe("scheduler.job.triggered", triggered)
        event_bus.subscribe("scheduler.job.completed", completed)

        scheduler.schedule_once(lambda: None, delay_seconds=0.01)

        assert len(scheduled.received) == 1
        assert isinstance(scheduled.received[0], JobScheduledEvent)

        _wait_until(lambda: len(completed.received) == 1)

        assert isinstance(triggered.received[0], JobTriggeredEvent)
        assert isinstance(completed.received[0], JobCompletedEvent)

    def test_failed_callback_publishes_failed_event(
        self,
        scheduler: Scheduler,
        event_bus: EventBus,
    ) -> None:
        failed = RecordingSubscriber()
        event_bus.subscribe("scheduler.job.failed", failed)

        def _boom() -> None:
            raise RuntimeError("boom")

        job = scheduler.schedule_once(_boom, delay_seconds=0.01)

        _wait_until(lambda: len(failed.received) == 1)

        assert isinstance(failed.received[0], JobFailedEvent)
        assert scheduler.get(job.id).status is JobStatus.FAILED
        assert isinstance(scheduler.get(job.id).failure, RuntimeError)

    def test_stores_metadata(
        self,
        scheduler: Scheduler,
    ) -> None:
        job = scheduler.schedule_once(
            lambda: None,
            delay_seconds=1.0,
            metadata={"origin": "test"},
        )

        assert job.metadata["origin"] == "test"
        scheduler.cancel(job.id)


# ---------------------------------------------------------------------
# schedule_interval()
# ---------------------------------------------------------------------


class TestScheduleInterval:
    def test_triggers_repeatedly(
        self,
        scheduler: Scheduler,
    ) -> None:
        calls: list[int] = []

        job = scheduler.schedule_interval(
            lambda: calls.append(1),
            interval_seconds=0.01,
        )

        _wait_until(lambda: len(calls) >= 3)

        scheduler.cancel(job.id)
        assert scheduler.get(job.id).status is JobStatus.CANCELLED

    def test_rejects_non_positive_interval(
        self,
        scheduler: Scheduler,
    ) -> None:
        with pytest.raises(InvalidScheduleError):
            scheduler.schedule_interval(lambda: None, interval_seconds=0)

    def test_rejects_negative_start_delay(
        self,
        scheduler: Scheduler,
    ) -> None:
        with pytest.raises(InvalidScheduleError):
            scheduler.schedule_interval(
                lambda: None,
                interval_seconds=1.0,
                start_delay_seconds=-1.0,
            )

    def test_recurring_job_stops_on_failure(
        self,
        scheduler: Scheduler,
    ) -> None:
        calls: list[int] = []

        def _fail_once() -> None:
            calls.append(1)
            raise RuntimeError("boom")

        job = scheduler.schedule_interval(
            _fail_once,
            interval_seconds=0.01,
        )

        _wait_until(lambda: scheduler.get(job.id).status is JobStatus.FAILED)
        triggered_after_failure = len(calls)

        time.sleep(0.05)

        assert len(calls) == triggered_after_failure


# ---------------------------------------------------------------------
# cancel()
# ---------------------------------------------------------------------


class TestCancel:
    def test_cancel_prevents_trigger(
        self,
        scheduler: Scheduler,
        event_bus: EventBus,
    ) -> None:
        cancelled = RecordingSubscriber()
        event_bus.subscribe("scheduler.job.cancelled", cancelled)

        calls: list[int] = []
        job = scheduler.schedule_once(
            lambda: calls.append(1),
            delay_seconds=0.05,
        )

        scheduler.cancel(job.id)

        assert scheduler.get(job.id).status is JobStatus.CANCELLED
        assert len(cancelled.received) == 1
        assert isinstance(cancelled.received[0], JobCancelledEvent)

        time.sleep(0.1)
        assert calls == []

    def test_cancel_raises_when_missing(
        self,
        scheduler: Scheduler,
    ) -> None:
        with pytest.raises(JobNotFoundError):
            scheduler.cancel("missing-job")

    def test_cancel_raises_when_already_cancelled(
        self,
        scheduler: Scheduler,
    ) -> None:
        job = scheduler.schedule_once(lambda: None, delay_seconds=1.0)
        scheduler.cancel(job.id)

        with pytest.raises(JobAlreadyCancelledError):
            scheduler.cancel(job.id)

    def test_cancel_raises_when_already_finished(
        self,
        scheduler: Scheduler,
    ) -> None:
        job = scheduler.schedule_once(lambda: None, delay_seconds=0.01)

        _wait_until(
            lambda: scheduler.get(job.id).status is JobStatus.COMPLETED
        )

        with pytest.raises(JobAlreadyFinishedError):
            scheduler.cancel(job.id)


# ---------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------


class TestRegistry:
    def test_get_raises_when_missing(
        self,
        scheduler: Scheduler,
    ) -> None:
        with pytest.raises(JobNotFoundError):
            scheduler.get("missing-job")

    def test_contains_and_count(
        self,
        scheduler: Scheduler,
    ) -> None:
        assert scheduler.count() == 0
        assert not scheduler.contains("missing-job")

        job = scheduler.schedule_once(lambda: None, delay_seconds=1.0)

        assert scheduler.contains(job.id)
        assert scheduler.count() == 1

        scheduler.cancel(job.id)

    def test_get_all_returns_snapshot(
        self,
        scheduler: Scheduler,
    ) -> None:
        job = scheduler.schedule_once(lambda: None, delay_seconds=1.0)

        all_jobs = scheduler.get_all()

        assert set(all_jobs) == {job.id}

        with pytest.raises(TypeError):
            all_jobs["x"] = object()  # type: ignore[index]

        scheduler.cancel(job.id)


# ---------------------------------------------------------------------
# shutdown()
# ---------------------------------------------------------------------


class TestShutdown:
    def test_shutdown_cancels_all_scheduled_jobs(
        self,
        scheduler: Scheduler,
    ) -> None:
        calls: list[int] = []

        job_one = scheduler.schedule_once(
            lambda: calls.append(1),
            delay_seconds=0.2,
        )
        # `start_delay_seconds` must be supplied explicitly here: it
        # defaults to `0.0` ("fire immediately"), which would give
        # this job's *first* trigger no real safety margin at all
        # before `shutdown()` runs below - an unintentional,
        # effectively-zero-margin race entirely unrelated to what this
        # test is verifying (that shutdown() cancels jobs that are
        # still genuinely pending). Matching `job_one`'s 0.2s margin
        # here restores that intent.
        job_two = scheduler.schedule_interval(
            lambda: calls.append(1),
            interval_seconds=0.2,
            start_delay_seconds=0.2,
        )

        scheduler.shutdown()

        assert scheduler.get(job_one.id).status is JobStatus.CANCELLED
        assert scheduler.get(job_two.id).status is JobStatus.CANCELLED

        time.sleep(0.3)
        assert calls == []

    def test_shutdown_leaves_an_already_running_job_running(
        self,
        scheduler: Scheduler,
    ) -> None:
        """
        Regression test for the `cancel()`/`_trigger()` race fixed
        alongside this test: a job whose callback has already started
        executing (`JobStatus.RUNNING`) must never be reported as
        `CANCELLED` by `shutdown()`/`cancel()` -- `cancel()` now
        raises `JobAlreadyFinishedError` for it instead (caught and
        skipped by `shutdown()`'s existing `except SchedulerError`),
        leaving the job's status truthfully `RUNNING` until its
        callback finishes.

        Deterministic (no wall-clock racing): the callback blocks on
        a `threading.Event` so the test can synchronize precisely on
        "the callback has started" before calling `shutdown()`,
        instead of relying on any timing margin.
        """

        started = threading.Event()
        proceed = threading.Event()

        def callback() -> None:
            started.set()
            proceed.wait(timeout=2.0)

        job = scheduler.schedule_once(callback, delay_seconds=0.0)

        assert started.wait(timeout=2.0), "callback never started"
        assert scheduler.get(job.id).status is JobStatus.RUNNING

        scheduler.shutdown()

        # The race is resolved *honestly*: the job is not falsely
        # reported as CANCELLED, and it is not left dangling either.
        assert scheduler.get(job.id).status is JobStatus.RUNNING

        proceed.set()

        _wait_until(
            lambda: scheduler.get(job.id).status is JobStatus.COMPLETED
        )
        assert scheduler.get(job.id).status is JobStatus.COMPLETED

    def test_cancel_raises_when_job_is_currently_running(
        self,
        scheduler: Scheduler,
    ) -> None:
        """
        Direct unit test for the same fix as
        `test_shutdown_leaves_an_already_running_job_running`, calling
        `cancel()` directly rather than through `shutdown()`.
        """

        started = threading.Event()
        proceed = threading.Event()

        def callback() -> None:
            started.set()
            proceed.wait(timeout=2.0)

        job = scheduler.schedule_once(callback, delay_seconds=0.0)

        assert started.wait(timeout=2.0), "callback never started"

        with pytest.raises(JobAlreadyFinishedError):
            scheduler.cancel(job.id)

        assert scheduler.get(job.id).status is JobStatus.RUNNING

        proceed.set()
        _wait_until(
            lambda: scheduler.get(job.id).status is JobStatus.COMPLETED
        )
