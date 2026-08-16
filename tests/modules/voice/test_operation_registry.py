"""
Unit tests for `parika.modules.voice.operation_registry.TtsOperationRegistry`.
"""

from __future__ import annotations

from parika.modules.voice.operation_registry import (
    TtsOperationRegistry,
    TtsOperationStatus,
)


def test_unknown_operation_has_no_status() -> None:
    registry = TtsOperationRegistry()

    assert registry.get_status("nope") is None
    assert registry.is_cancelled("nope") is False


def test_begin_then_complete_reports_completed() -> None:
    registry = TtsOperationRegistry()

    registry.begin("op-1")
    assert registry.get_status("op-1") is TtsOperationStatus.RUNNING
    assert registry.is_cancelled("op-1") is False

    registry.complete("op-1")
    assert registry.get_status("op-1") is TtsOperationStatus.COMPLETED
    assert registry.is_cancelled("op-1") is False


def test_begin_then_fail_reports_failed() -> None:
    registry = TtsOperationRegistry()

    registry.begin("op-1")
    registry.fail("op-1")

    assert registry.get_status("op-1") is TtsOperationStatus.FAILED


def test_cancel_while_running_returns_true_and_reports_cancelled() -> None:
    registry = TtsOperationRegistry()

    registry.begin("op-1")

    assert registry.cancel("op-1") is True
    assert registry.is_cancelled("op-1") is True
    assert registry.get_status("op-1") is TtsOperationStatus.CANCELLED


def test_cancel_of_unknown_operation_preemptively_cancels() -> None:
    """
    A caller may call `stop` before the matching `speak` request has
    even reached `begin()` -- the cancellation must still be honored
    (see `begin()`'s own docstring).
    """

    registry = TtsOperationRegistry()

    assert registry.cancel("op-never-begun") is True
    assert registry.is_cancelled("op-never-begun") is True

    registry.begin("op-never-begun")

    assert registry.get_status("op-never-begun") is TtsOperationStatus.CANCELLED
    assert registry.is_cancelled("op-never-begun") is True


def test_cancel_after_completed_returns_false() -> None:
    registry = TtsOperationRegistry()

    registry.begin("op-1")
    registry.complete("op-1")

    assert registry.cancel("op-1") is False
    assert registry.get_status("op-1") is TtsOperationStatus.COMPLETED


def test_cancel_after_failed_returns_false() -> None:
    registry = TtsOperationRegistry()

    registry.begin("op-1")
    registry.fail("op-1")

    assert registry.cancel("op-1") is False
    assert registry.get_status("op-1") is TtsOperationStatus.FAILED


def test_cancel_twice_returns_false_the_second_time() -> None:
    registry = TtsOperationRegistry()

    registry.begin("op-1")

    assert registry.cancel("op-1") is True
    assert registry.cancel("op-1") is False


def test_complete_never_overrides_cancellation() -> None:
    registry = TtsOperationRegistry()

    registry.begin("op-1")
    registry.cancel("op-1")
    registry.complete("op-1")

    assert registry.get_status("op-1") is TtsOperationStatus.CANCELLED


def test_fail_never_overrides_cancellation() -> None:
    registry = TtsOperationRegistry()

    registry.begin("op-1")
    registry.cancel("op-1")
    registry.fail("op-1")

    assert registry.get_status("op-1") is TtsOperationStatus.CANCELLED


def test_evicts_oldest_entries_beyond_capacity() -> None:
    registry = TtsOperationRegistry(max_tracked_operations=3)

    for index in range(5):
        registry.begin(f"op-{index}")

    assert registry.get_status("op-0") is None
    assert registry.get_status("op-1") is None
    assert registry.get_status("op-2") is TtsOperationStatus.RUNNING
    assert registry.get_status("op-3") is TtsOperationStatus.RUNNING
    assert registry.get_status("op-4") is TtsOperationStatus.RUNNING
