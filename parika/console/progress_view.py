"""
PARIKA Console - Execution Progress Rendering

Renders PARIKA's real execution-progress events (Phase 3.5b) live, in
place of any artificial "loading"/"thinking" message. The Console
shares the same in-process, synchronous `EventBus` as every Core
component, so every event below is rendered in real time, with no
buffering and no transport boundary.

Subscribes once, for the process lifetime, to:

- The four generic `progress.*` channels (`progress.started`,
  `progress.progress`, `progress.completed`, `progress.failed`) --
  carrying `ProgressEvent`s from `memory.search`, `knowledge.search`,
  Brain's own `brain.execution` tree (`brain.execution`,
  `brain.planning`, `brain.execute_goal`), and any present or future
  Tool/Module's own `ProgressReporter` usage. This is the one,
  ecosystem-wide, generic channel every present and future source
  publishes to -- this module never hardcodes a specific Tool or
  Module's `source_id`; unrecognized `source_id`s still render, using
  a best-effort, generic label.
- The existing `capability.execution.started/completed/failed` events
  (already published by `CapabilityExecutor`, unchanged), which
  already fully cover "Executing Capability" at the capability
  granularity.
- The existing `tool.executed`/`tool.execution_failed` events
  (already published by `ToolManager`, unchanged), covering "Calling
  Tool" once a tool call actually completes.

This module contains no business logic and never fabricates a status
message on another component's behalf: it only renders what each
component already, independently reported about its own work.
"""

from __future__ import annotations

import sys
from typing import Any, TextIO

from parika.core.capability_executor.events import (
    CapabilityExecutionCompletedEvent,
    CapabilityExecutionFailedEvent,
    CapabilityExecutionStartedEvent,
)
from parika.core.event_bus.event_bus import EventBus
from parika.core.tool_manager.events import ToolExecuted, ToolExecutionFailed
from parika.core.utilities.progress import ProgressEvent, ProgressStage

from .colors import Ansi, colorize

_STAGE_LABELS: dict[str, str] = {
    "memory.search": "Searching Memory",
    "knowledge.search": "Searching Knowledge",
    "brain.execution": "Thinking",
    "brain.planning": "Planning",
    "brain.execute_goal": "Executing Goal",
}
"""
Friendly display labels for the `source_id`s this phase introduces.
Deliberately small and closed -- every other, present or future,
`source_id` (from any Tool/Module's own `ProgressReporter` usage)
falls back to `_humanize()` below, so nothing here needs to change
when a new Tool or Module starts reporting progress.
"""


def _humanize(source_id: str) -> str:
    """
    Best-effort display label for a `source_id` with no specific entry
    in `_STAGE_LABELS`, so every present and future Tool/Module's own
    progress reporting renders with zero code change here.
    """

    return source_id.replace(".", " ").replace("_", " ").strip().title() or source_id


def _label(source_id: str) -> str:
    return _STAGE_LABELS.get(source_id, _humanize(source_id))


class ConsoleProgressRenderer:
    """
    Subscribes to PARIKA's execution-progress channels and prints one
    short status line per event, live, exactly as it happens.
    """

    def __init__(
        self,
        event_bus: EventBus,
        *,
        stream: TextIO | None = None,
        color: bool = True,
    ) -> None:
        """
        Initialize the renderer. Does not subscribe until `start()` is
        called.

        Args:
            event_bus:
                The runtime's `EventBus`, shared with every Core
                component.

            stream:
                Output stream. Defaults to `sys.stdout`.

            color:
                Whether to dim-style rendered lines.
        """

        self._event_bus = event_bus
        self._stream: TextIO = stream if stream is not None else sys.stdout
        self._color = color
        self._subscribed = False

    def start(self) -> None:
        """
        Begin rendering. Idempotent -- calling twice has no effect.
        """

        if self._subscribed:
            return

        for stage in ProgressStage:
            self._event_bus.subscribe(f"progress.{stage.value}", self._on_progress_event)

        self._event_bus.subscribe(
            "capability.execution.started", self._on_capability_started
        )
        self._event_bus.subscribe(
            "capability.execution.completed", self._on_capability_completed
        )
        self._event_bus.subscribe(
            "capability.execution.failed", self._on_capability_failed
        )
        self._event_bus.subscribe("tool.executed", self._on_tool_executed)
        self._event_bus.subscribe(
            "tool.execution_failed", self._on_tool_execution_failed
        )

        self._subscribed = True

    def stop(self) -> None:
        """
        Stop rendering and unsubscribe. Idempotent.
        """

        if not self._subscribed:
            return

        for stage in ProgressStage:
            self._event_bus.unsubscribe(f"progress.{stage.value}", self._on_progress_event)

        self._event_bus.unsubscribe(
            "capability.execution.started", self._on_capability_started
        )
        self._event_bus.unsubscribe(
            "capability.execution.completed", self._on_capability_completed
        )
        self._event_bus.unsubscribe(
            "capability.execution.failed", self._on_capability_failed
        )
        self._event_bus.unsubscribe("tool.executed", self._on_tool_executed)
        self._event_bus.unsubscribe(
            "tool.execution_failed", self._on_tool_execution_failed
        )

        self._subscribed = False

    def suspend(self) -> None:
        """
        No-op: `ConsoleProgressRenderer` (Debug Mode) writes one
        complete, newline-terminated line per event and never repaints
        a shared line, so there is nothing to suspend -- present only
        so callers (see `app.py`'s `_handle_streamed_chat()`) can treat
        either rendering mode identically.
        """

    def resume(self) -> None:
        """No-op counterpart to `suspend()` -- see its docstring."""

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _write(self, indent_level: int, text: str) -> None:
        line = f"{'  ' * indent_level}[{text}]"
        self._stream.write(colorize(line, Ansi.DIM, enabled=self._color))
        self._stream.write("\n")
        self._stream.flush()

    def _on_progress_event(self, event: Any) -> None:
        if not isinstance(event, ProgressEvent):
            return

        indent_level = max(0, len(event.progress_path) - 1)
        label = _label(event.source_id)

        if event.stage is ProgressStage.STARTED:
            self._write(indent_level, f"{label}...")

        elif event.stage is ProgressStage.COMPLETED:
            self._write(indent_level, f"{label}... done")

        elif event.stage is ProgressStage.FAILED:
            suffix = f": {event.message}" if event.message else ""
            self._write(indent_level, f"{label}... failed{suffix}")

        elif event.stage is ProgressStage.PROGRESS and event.message:
            self._write(indent_level, f"{label}: {event.message}")

    def _on_capability_started(self, event: Any) -> None:
        if isinstance(event, CapabilityExecutionStartedEvent):
            self._write(
                1,
                f"Executing capability: {event.capability_id} "
                f"({event.backend.value})...",
            )

    def _on_capability_completed(self, event: Any) -> None:
        if isinstance(event, CapabilityExecutionCompletedEvent):
            self._write(1, f"Executing capability: {event.capability_id}... done")

    def _on_capability_failed(self, event: Any) -> None:
        if isinstance(event, CapabilityExecutionFailedEvent):
            self._write(
                1,
                f"Executing capability: {event.capability_id}... failed: "
                f"{event.error_message}",
            )

    def _on_tool_executed(self, event: Any) -> None:
        if isinstance(event, ToolExecuted):
            self._write(2, f"Calling Tool: {event.tool_id}... done")

    def _on_tool_execution_failed(self, event: Any) -> None:
        if isinstance(event, ToolExecutionFailed):
            self._write(2, f"Calling Tool: {event.tool_id}... failed")
