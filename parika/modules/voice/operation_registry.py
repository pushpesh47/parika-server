"""
PARIKA Voice Module - TTS Operation Registry

Tracks the lifecycle of independently-controllable `text_to_speech`
operations, keyed by a caller-supplied `operation_id`, so a separate,
later "Stop Speaking" request can cooperatively cancel an in-progress
synthesis -- see `driver_tts.py`'s chunked synthesis loop, which
checks `is_cancelled()` between chunks (per
`text_chunking.split_into_speech_chunks()`).

This is deliberately a small, Voice-specific concept, distinct from
(and never a replacement for) `ProgressReporter`/`ToolManager`'s
execution-lifecycle guard: `ProgressReporter` answers "did this Tool
execution start/finish exactly once", which remains entirely the
shared `ToolManager` guard's job (see
`parika.core.tool_manager.tool_manager._execute_driver_with_progress_
guard`) and is unaffected by anything in this module.
`TtsOperationRegistry` instead answers a *different* question a
completed-or-still-running Tool execution's *caller* needs answered:
"does the user still want to hear this audio". Stopping a TTS
operation never cancels, fails, or otherwise touches the Tool
execution's own progress lifecycle -- see `driver_tts.py`'s own
docstring for exactly how the two interact.

Registered once, as a shared singleton, through the existing
`ServiceContainer` (see `parika/interfaces/runtime.py`) -- never a
global/module-level singleton -- so every `TextToSpeechToolDriver`
instance and the Voice API's `/voice/speak/{operation_id}/stop`
handler observe the same registry.
"""

from __future__ import annotations

from collections import OrderedDict
from enum import StrEnum
from threading import RLock

DEFAULT_MAX_TRACKED_OPERATIONS = 1000


class TtsOperationStatus(StrEnum):
    """
    Lifecycle status of one `text_to_speech` operation, as tracked by
    `TtsOperationRegistry`.
    """

    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class TtsOperationRegistry:
    """
    Thread-safe registry of in-progress/finished `text_to_speech`
    operations, keyed by `operation_id`.
    """

    def __init__(self, *, max_tracked_operations: int = DEFAULT_MAX_TRACKED_OPERATIONS) -> None:
        self._lock = RLock()
        self._statuses: OrderedDict[str, TtsOperationStatus] = OrderedDict()
        self._max_tracked_operations = max_tracked_operations

    def begin(self, operation_id: str) -> None:
        """
        Record that synthesis for `operation_id` has started.

        A no-op if `operation_id` was already cancelled *before*
        synthesis started (a caller that calls `stop` immediately
        after `speak`, before this Module's Tool execution has even
        begun, must still result in the operation never producing
        audio) -- see `driver_tts.py`'s first `is_cancelled()` check.
        """

        with self._lock:
            if self._statuses.get(operation_id) is TtsOperationStatus.CANCELLED:
                return

            self._statuses[operation_id] = TtsOperationStatus.RUNNING
            self._evict_oldest_if_over_capacity()

    def is_cancelled(self, operation_id: str) -> bool:
        """
        Whether `operation_id` has been cancelled (checked by
        `driver_tts.py` between synthesis chunks).
        """

        with self._lock:
            return self._statuses.get(operation_id) is TtsOperationStatus.CANCELLED

    def cancel(self, operation_id: str) -> bool:
        """
        Request cancellation of `operation_id`.

        Returns:
            `True` if the operation was tracked and not already in a
            terminal state (or was not yet tracked at all -- a
            preemptive cancel racing ahead of `begin()` is still
            honored). `False` if the operation already finished
            (`completed`/`failed`) or was already cancelled.
        """

        with self._lock:
            current = self._statuses.get(operation_id)

            if current in (
                TtsOperationStatus.COMPLETED,
                TtsOperationStatus.FAILED,
                TtsOperationStatus.CANCELLED,
            ):
                return False

            self._statuses[operation_id] = TtsOperationStatus.CANCELLED
            self._evict_oldest_if_over_capacity()

            return True

    def complete(self, operation_id: str) -> None:
        """
        Record that `operation_id` finished successfully, unless it
        was already cancelled (cancellation always wins).
        """

        with self._lock:
            if self._statuses.get(operation_id) is not TtsOperationStatus.CANCELLED:
                self._statuses[operation_id] = TtsOperationStatus.COMPLETED

    def fail(self, operation_id: str) -> None:
        """
        Record that `operation_id` failed, unless it was already
        cancelled (cancellation always wins).
        """

        with self._lock:
            if self._statuses.get(operation_id) is not TtsOperationStatus.CANCELLED:
                self._statuses[operation_id] = TtsOperationStatus.FAILED

    def get_status(self, operation_id: str) -> TtsOperationStatus | None:
        """The current status of `operation_id`, or `None` if unknown."""

        with self._lock:
            return self._statuses.get(operation_id)

    def _evict_oldest_if_over_capacity(self) -> None:
        while len(self._statuses) > self._max_tracked_operations:
            self._statuses.popitem(last=False)
