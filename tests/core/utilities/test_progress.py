"""
Unit tests for the Progress Reporting utility
(parika.core.utilities.progress).
"""

from __future__ import annotations

import logging

from parika.core.event_bus.event_bus import EventBus
from parika.core.utilities.progress import (
    NullProgressReporter,
    ProgressEvent,
    ProgressReporter,
    ProgressStage,
)


class _FakeLogger:
    def get_logger(self, name: str) -> logging.Logger:
        return logging.getLogger(name)


def _build_event_bus() -> EventBus:
    return EventBus(_FakeLogger())  # type: ignore[arg-type]


def test_started_publishes_specific_and_generic_channels() -> None:
    event_bus = _build_event_bus()
    received: list[tuple[str, ProgressEvent]] = []

    event_bus.subscribe(
        "filesystem.search.started",
        lambda event: received.append(("specific", event)),
    )
    event_bus.subscribe(
        "progress.started",
        lambda event: received.append(("generic", event)),
    )

    reporter = ProgressReporter(event_bus, "filesystem.search")
    reporter.started(message="Searching directory...")

    assert len(received) == 2
    channels = {channel for channel, _ in received}
    assert channels == {"specific", "generic"}

    for _, event in received:
        assert event.source_id == "filesystem.search"
        assert event.stage is ProgressStage.STARTED
        assert event.message == "Searching directory..."
        assert event.progress_id == reporter.progress_id
        assert event.parent_progress_id is None
        assert event.progress_path == (reporter.progress_id,)


def test_progress_computes_percent_from_current_and_total() -> None:
    event_bus = _build_event_bus()
    captured: list[ProgressEvent] = []
    event_bus.subscribe("progress.progress", captured.append)

    reporter = ProgressReporter(event_bus, "coding.index")
    reporter.progress(current=530, total=1200, message="530 / 1200 files")

    assert len(captured) == 1
    event = captured[0]
    assert event.current == 530
    assert event.total == 1200
    assert event.percent is not None
    assert round(event.percent, 2) == round((530 / 1200) * 100, 2)


def test_progress_percent_is_none_without_total() -> None:
    event_bus = _build_event_bus()
    captured: list[ProgressEvent] = []
    event_bus.subscribe("progress.progress", captured.append)

    ProgressReporter(event_bus, "coding.search").progress(message="Searching...")

    assert captured[0].percent is None


def test_child_reporter_carries_parent_identity_and_inherits_task_id() -> None:
    event_bus = _build_event_bus()
    captured: list[ProgressEvent] = []
    completed: list[ProgressEvent] = []
    event_bus.subscribe("progress.started", captured.append)
    event_bus.subscribe("progress.completed", completed.append)

    root = ProgressReporter(
        event_bus, "repository_intelligence.index_workspace", task_id="task-1"
    )
    root.started(message="Repository Indexing")

    child = root.child("repository_intelligence.discover_workspace")
    child.started(message="Discovering repositories...")

    grandchild = child.child("coding.index.scan_files")
    grandchild.started(message="Scanning files...")

    assert len(captured) == 3
    root_event, child_event, grandchild_event = captured

    assert child_event.parent_progress_id == root.progress_id
    assert child_event.task_id == "task-1"
    assert child_event.progress_path == (root.progress_id, child.progress_id)

    assert grandchild_event.parent_progress_id == child.progress_id
    assert grandchild_event.task_id == "task-1"
    assert grandchild_event.progress_path == (
        root.progress_id,
        child.progress_id,
        grandchild.progress_id,
    )

    # Stable for the lifetime of each node.
    child.completed(message="Discovered.")
    assert completed[-1].progress_id == child.progress_id
    assert completed[-1].parent_progress_id == root.progress_id


def test_child_can_override_task_id_for_its_own_task() -> None:
    event_bus = _build_event_bus()
    captured: list[ProgressEvent] = []
    event_bus.subscribe("progress.started", captured.append)

    root = ProgressReporter(event_bus, "coding.execute_task", task_id="task-1")
    child = root.child("coding.plan_change", task_id="task-2")
    child.started()

    assert captured[0].task_id == "task-2"
    assert captured[0].parent_progress_id == root.progress_id


def test_failed_and_completed_publish_expected_stage() -> None:
    event_bus = _build_event_bus()
    captured: list[ProgressEvent] = []
    event_bus.subscribe("shell.execute.failed", captured.append)
    event_bus.subscribe("shell.execute.completed", captured.append)

    reporter = ProgressReporter(event_bus, "shell.execute")
    reporter.failed(message="Command failed.")
    reporter.completed(message="Command finished.")

    assert [event.stage for event in captured] == [
        ProgressStage.FAILED,
        ProgressStage.COMPLETED,
    ]


def test_null_progress_reporter_never_raises_without_subscribers() -> None:
    reporter = NullProgressReporter("test.source")
    reporter.started(message="ignored")
    reporter.progress(current=1, total=2)
    reporter.completed()
    reporter.failed()


def test_metadata_kwargs_are_carried_on_event() -> None:
    event_bus = _build_event_bus()
    captured: list[ProgressEvent] = []
    event_bus.subscribe("progress.started", captured.append)

    ProgressReporter(event_bus, "repository_intelligence.index_repository").started(
        message="Indexing repository...", repository="A"
    )

    assert captured[0].metadata == {"repository": "A"}
