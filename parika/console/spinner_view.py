"""
PARIKA Console - Transient Spinner Progress Rendering (Normal Mode)

Renders PARIKA's real execution-progress events (the same events
`ConsoleProgressRenderer` in `progress_view.py` renders verbosely for
Debug Mode) as a single, transient, spinner status line -- the
Console's default "Normal Mode" UX, in the style of Claude Code,
Cursor CLI, and Gemini CLI.

This module is a pure View: it subscribes to the same, already
existing, unmodified execution-progress channels (`progress.*`,
`capability.execution.*`, `tool.executed`/`tool.execution_failed`) as
`ConsoleProgressRenderer`, and never publishes anything back, calls
into Brain/Planner/Tools/Providers, or otherwise influences execution
in any way. It only renders what other components already,
independently, reported about their own work.

Rendering model
----------------
Every `*.started`-shaped event increments an in-flight counter and
records a short, human-friendly status message (translated from the
internal, technical identifier -- e.g. `"vision.describe_image"` --
entirely inside this module; internal identifiers are never changed
or exposed to the end user). Every matching
`*.completed`/`*.failed`-shaped event decrements the counter. A
background thread repaints one line -- a
rotating unicode braille spinner glyph followed by the current status
message -- in place, using a carriage return (`\\r`), roughly every
80-120ms, for as long as the counter is above zero. As soon as the
counter returns to zero (the outermost `brain.execution` node's own
`completed`/`failed` event, by construction, always fires last), the
line is cleared synchronously, before the triggering event handler
returns -- so by the time `InterfaceSession.submit_text()` returns
control to the Console's REPL loop and the final answer is printed,
no spinner residue can remain, regardless of the background thread's
own timing.

Thread-safety
-------------
A single lock guards every mutation of, and every render/clear of, the
shared status line, so the background render thread and whichever
thread publishes execution-progress events (in practice, the same
thread that calls `InterfaceSession.submit_text()`, since `EventBus`
dispatches synchronously) never interleave their writes. `suspend()`/
`resume()` extend the same guarantee to any other console output that
needs to share the terminal with this renderer (e.g. streamed answer
tokens) without another redesign of either side.

Presentation
------------
The line is indented two spaces so it visually reads as part of the
current conversation turn, not as another top-level prompt. Only the
orbit glyph animates -- the status text next to it stays put frame to
frame -- and the glyph is colored cyan while the status text is dimmed
gray, so the one thing that changes every frame draws the eye, and the
status text reads as secondary, momentary context.

Dynamic waiting messages, elapsed time, and the terminal title
----------------------------------------------------------------
Three more presentation-only refinements layer on top of the same
label/counter state above, all driven from the same render loop and
none of them ever fabricating an event that did not happen:

- Whenever the currently displayed label is one of a small, closed
  set of *generic* waiting statuses (`_WAITING_LABELS` -- Brain
  thinking about what to do next, or the model composing its answer)
  and stays unchanged for `_ROTATION_INTERVAL_SECONDS`, the line
  rotates through `_WAITING_ROTATION`'s neutral filler phrases so a
  genuinely idle wait does not feel frozen. Concrete labels (Vision,
  OCR, Filesystem, Web, Shell, etc.) never rotate, and any real event
  immediately replaces whatever was showing, rotated or not.
- Once a single turn's total elapsed time crosses
  `_ELAPSED_TIME_THRESHOLD_SECONDS`, the line appends `" (Ns)"`,
  updated every frame, removed the instant the turn completes.
- The terminal's window/tab title (`terminal_title.py`) mirrors
  whatever label is currently showing (without the elapsed-time
  suffix) while a turn is in flight, and reverts to the idle title
  the instant the turn completes.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Any, TextIO

from parika.core.capability_executor.events import (
    CapabilityExecutionCompletedEvent,
    CapabilityExecutionFailedEvent,
    CapabilityExecutionStartedEvent,
)
from parika.core.capability_executor.execution_backend import ExecutionBackend
from parika.core.event_bus.event_bus import EventBus
from parika.core.tool_manager.events import ToolExecuted, ToolExecutionFailed
from parika.core.utilities.progress import ProgressEvent, ProgressStage

from .colors import Ansi, colorize
from .terminal_title import IDLE_TITLE, set_terminal_title

SPINNER_FRAMES: tuple[str, ...] = (
    "\u280b",  # ⠋
    "\u2819",  # ⠙
    "\u2839",  # ⠹
    "\u2838",  # ⠸
    "\u283c",  # ⠼
    "\u2834",  # ⠴
    "\u2826",  # ⠦
    "\u2827",  # ⠧
    "\u2807",  # ⠇
    "\u280f",  # ⠏
)
"""
Rotating braille spinner glyphs, in display order.
"""

FRAME_INTERVAL_SECONDS = 0.09
"""Roughly one frame every 90ms, within the requested 80-120ms range."""

_IDLE_POLL_SECONDS = 0.2
"""
How long the render thread waits, at most, between checks while no
operation is in flight, before re-checking whether it should stop.
Kept short so `stop()` never blocks noticeably.
"""

_INDENT = "  "
"""
Leading spaces the spinner line is drawn with, so it visually reads as
part of the current conversation turn (indented under the prompt line
that started it) rather than as another top-level prompt of its own.
"""

_DEFAULT_TOOL_LABEL = "Working..."
_DEFAULT_CAPABILITY_LABEL = "Working..."
"""
A single, generic, present-participle status word covers every
present or future capability/tool with no more specific mapping below
-- one generic word, not several ("Processing...", "Running tool...",
etc.), so unmapped internal activity reads as one more step of the
same ongoing phase instead of a confusing new one.
"""

_SOURCE_LABELS: dict[str, str] = {
    "memory.search": "Checking context...",
    "knowledge.search": "Gathering information...",
    "brain.execution": "Thinking...",
    "brain.planning": "Planning...",
    "brain.execute_goal": "Working...",
}
"""
Friendly labels for the small, closed set of `source_id`s Brain's own
progress tree reports (Phase 3.5b). Deliberately collapsed to a small
number of user-facing phases (`Checking context...` covers both
the root `brain.execution` node and the memory/knowledge search steps
nested under it, since they all precede any actual planning/tool work)
so a turn reads as a handful of meaningful phases rather than one line
per internal event. Every other, present or future, `source_id` (from
any Tool/Module's own `ProgressReporter` usage) falls back to
`_KEYWORD_LABELS` below, then to `_DEFAULT_CAPABILITY_LABEL`.
"""

_KEYWORD_LABELS: tuple[tuple[str, str, str], ...] = (
    # (keyword found in an internal identifier, tool-backed label, provider-backed label)
    ("vision", "Analyzing image...", "Analyzing image..."),
    ("ocr", "Extracting text...", "Extracting text..."),
    ("filesystem", "Reading files...", "Reading files..."),
    ("chat", "Generating response...", "Generating response..."),
    ("web", "Searching the web...", "Searching the web..."),
    ("shell", "Running command...", "Running command..."),
    ("repository", "Exploring project...", "Exploring project..."),
    ("coding", "Analyzing code...", "Analyzing code..."),
    ("video", "Processing video...", "Processing video..."),
    ("image", "Generating image...", "Generating image..."),
    ("weather", "Checking weather...", "Checking weather..."),
    ("currency", "Converting currency...", "Converting currency..."),
    ("news", "Fetching news...", "Fetching news..."),
    ("document", "Reading document...", "Reading document..."),
    ("memory", "Managing memory...", "Managing memory..."),
    ("runtime", "Checking runtime info...", "Checking runtime info..."),
    # Checked before the generic "voice" fallback below, so
    # `voice.speech_to_text`/`tool.voice_speech_to_text`/
    # `voice.provider_speech_to_text` and their text-to-speech
    # counterparts each render their own specific label.
    ("speech_to_text", "Transcribing speech...", "Transcribing speech..."),
    ("text_to_speech", "Speaking...", "Speaking..."),
    ("voice", "Processing speech...", "Processing speech..."),
)
"""
Best-effort, keyword-based fallback so every present and future
capability/tool/source identifier renders a sensible, non-technical
label with zero code change here, without this module ever hardcoding
a closed list of every Tool/Module that exists today.
"""


def _keyword_label(identifier: str, *, provider: bool) -> str | None:
    lowered = identifier.lower()

    for keyword, tool_label, provider_label in _KEYWORD_LABELS:
        if keyword in lowered:
            return provider_label if provider else tool_label

    return None


def _source_label(source_id: str) -> str:
    if source_id in _SOURCE_LABELS:
        return _SOURCE_LABELS[source_id]

    return _keyword_label(source_id, provider=False) or _DEFAULT_CAPABILITY_LABEL


def _capability_label(capability_id: str, backend: ExecutionBackend) -> str:
    is_provider = backend is ExecutionBackend.PROVIDER

    label = _keyword_label(capability_id, provider=is_provider)

    if label is not None:
        return label

    return _DEFAULT_CAPABILITY_LABEL


def _tool_label(tool_id: str) -> str:
    return _keyword_label(tool_id, provider=False) or _DEFAULT_TOOL_LABEL


_WAITING_ROTATION: tuple[str, ...] = (
    "Connecting ideas...",
    "Exploring possibilities...",
    "Gathering insights...",
    "Analyzing information...",
    "Organizing information...",
    "Building the response...",
    "Reviewing the response...",
    "Refining the response...",
    "Checking final details...",
    "Finalizing response...",
)
"""
Neutral filler phrases shown, in order, once a *generic* waiting
status (see `_WAITING_LABELS` below) has stayed on screen, unchanged,
for `_ROTATION_INTERVAL_SECONDS` -- purely to keep a genuinely idle
wait from feeling frozen while nothing more specific is happening yet.
Never shown in place of a concrete label (e.g. `Searching the web...`,
`Analyzing image...`): those already describe real, currently
happening work, and rotating away from them would display something
that is not actually happening -- never faking execution.
"""

_ROTATION_INTERVAL_SECONDS = 4.0
"""How long a generic waiting status is shown before advancing to the
next `_WAITING_ROTATION` phrase."""

_ELAPSED_TIME_THRESHOLD_SECONDS = 10.0
"""
Once a single turn's total wait -- from the very first `*.started`
event to now, regardless of how many labels it has shown along the
way -- crosses this threshold, the rendered line starts appending the
elapsed time (e.g. `Thinking... (12s)`), so a genuinely slow turn is
honest about how long it has taken instead of pretending nothing
changed. Removed the instant the turn completes, along with the rest
of the line.
"""

_WAITING_LABELS: frozenset[str] = frozenset(
    {
        _SOURCE_LABELS["brain.execution"],  # "Thinking..."
        _SOURCE_LABELS["brain.planning"],  # "Planning..."
        _SOURCE_LABELS["brain.execute_goal"],  # "Working..."
        _SOURCE_LABELS["memory.search"],  # "Checking context..."
        _SOURCE_LABELS["knowledge.search"],  # "Gathering information..."
        _DEFAULT_TOOL_LABEL,  # "Working..."
        _DEFAULT_CAPABILITY_LABEL,  # "Working..."
        "Generating response...",  # the "chat" entry in _KEYWORD_LABELS
    }
)
"""
The closed set of *generic* status labels -- Brain thinking about what
to do next, or the model composing its final answer -- eligible for
`_WAITING_ROTATION` once they have stayed unchanged for
`_ROTATION_INTERVAL_SECONDS`. Every other label this module renders
(every `_KEYWORD_LABELS` entry other than `"chat"`: Vision, OCR,
Filesystem, Web, Shell, Repository, Coding) describes real, concrete
work a Tool/Capability is actually doing right now and is never
rotated away from. The moment one of those fires, whatever generic
waiting status (and rotation) was showing is immediately replaced by
it -- exactly like any other label change already was before this.
"""


class SpinnerProgressRenderer:
    """
    Subscribes to PARIKA's execution-progress channels -- the exact
    same channels `ConsoleProgressRenderer` (Debug Mode) subscribes
    to -- and renders them as a single, transient, spinner status
    line instead of one printed line per event (Normal Mode).

    Never affects execution: purely a View over events other
    components already publish independently of whether anything is
    rendering them at all.
    """

    def __init__(
        self,
        event_bus: EventBus,
        *,
        stream: TextIO | None = None,
        color: bool = True,
        frame_interval: float = FRAME_INTERVAL_SECONDS,
    ) -> None:
        """
        Initialize the renderer. Does not subscribe, and starts no
        background thread, until `start()` is called.

        Args:
            event_bus:
                The runtime's `EventBus`, shared with every Core
                component.

            stream:
                Output stream. Defaults to `sys.stdout`.

            color:
                Whether to color the spinner glyph.

            frame_interval:
                Seconds between spinner frame advances.
        """

        self._event_bus = event_bus
        self._stream: TextIO = stream if stream is not None else sys.stdout
        self._color = color
        self._frame_interval = frame_interval

        self._subscribed = False

        self._lock = threading.Lock()
        self._active = 0
        self._message = ""
        self._rendered_width = 0
        self._frame_index = 0
        self._suspended = False

        # Dynamic waiting-message rotation (see `_WAITING_LABELS`/
        # `_WAITING_ROTATION`) and long-running elapsed-time display
        # (see `_ELAPSED_TIME_THRESHOLD_SECONDS`) -- both purely
        # presentational, and both reset every time the counter
        # returns to (or leaves) zero, i.e. once per turn.
        self._turn_started_at: float | None = None
        self._is_waiting = False
        self._waiting_since = 0.0
        self._title_text = ""

        self._wake_event = threading.Event()
        self._stop_event = threading.Event()
        self._render_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Begin rendering: subscribe to events and start the background
        render thread. Idempotent -- calling twice has no effect.
        """

        if self._subscribed:
            return

        for stage in ProgressStage:
            self._event_bus.subscribe(
                f"progress.{stage.value}", self._on_progress_event
            )

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

        with self._lock:
            self._active = 0
            self._message = ""
            self._rendered_width = 0
            self._frame_index = 0
            self._suspended = False
            self._turn_started_at = None
            self._is_waiting = False
            self._waiting_since = 0.0
            self._title_text = IDLE_TITLE

        set_terminal_title(IDLE_TITLE)

        self._stop_event.clear()
        self._render_thread = threading.Thread(
            target=self._render_loop,
            name="parika-cli-spinner",
            daemon=True,
        )
        self._render_thread.start()

    def stop(self) -> None:
        """
        Stop rendering: unsubscribe, stop the background render
        thread, and clear any currently rendered line so the terminal
        is left clean. Idempotent, and safe to call from a
        `KeyboardInterrupt` handler.
        """

        if not self._subscribed:
            return

        for stage in ProgressStage:
            self._event_bus.unsubscribe(
                f"progress.{stage.value}", self._on_progress_event
            )

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

        self._stop_event.set()
        self._wake_event.set()

        render_thread = self._render_thread

        if render_thread is not None:
            render_thread.join(timeout=1.0)
            self._render_thread = None

        with self._lock:
            self._clear_locked()
            self._active = 0
            self._message = ""
            self._suspended = False
            self._turn_started_at = None
            self._is_waiting = False
            self._title_text = IDLE_TITLE

        set_terminal_title(IDLE_TITLE)

    def suspend(self) -> None:
        """
        Immediately clear the currently rendered line (if any) and
        stop repainting until `resume()` is called, without losing
        track of in-flight progress (the started/completed counter is
        untouched).

        Lets another piece of console output -- concretely, streamed
        answer tokens (see `app.py`'s `_handle_streamed_chat()`) --
        safely share the terminal with this renderer: once suspended,
        the background render thread performs no further writes at
        all, so external code may write to the same stream without
        risking an interleaved write. Idempotent, and safe to call
        even when not started or already suspended.
        """

        with self._lock:
            self._suspended = True
            self._clear_locked()

        self._wake_event.set()

    def resume(self) -> None:
        """
        Undo `suspend()`: the render thread starts repainting again
        (from the next frame) if any operation is still in flight.
        Idempotent, and safe to call even when not suspended.
        """

        with self._lock:
            self._suspended = False

        self._wake_event.set()

    # ------------------------------------------------------------------
    # Render thread
    # ------------------------------------------------------------------

    def _render_loop(self) -> None:
        while not self._stop_event.is_set():
            with self._lock:
                should_draw = self._active > 0 and not self._suspended

                if should_draw:
                    self._draw_locked()
                else:
                    self._clear_locked()

            if should_draw:
                self._stop_event.wait(self._frame_interval)
            else:
                self._wake_event.wait(_IDLE_POLL_SECONDS)
                self._wake_event.clear()

    def _draw_locked(self) -> None:
        frame = SPINNER_FRAMES[self._frame_index % len(SPINNER_FRAMES)]

        base_display = self._current_display_message_locked()
        self._update_title_locked(base_display)
        display = self._with_elapsed_suffix_locked(base_display)

        plain = f"{_INDENT}{frame} {display}" if display else f"{_INDENT}{frame}"

        glyph = colorize(frame, Ansi.CYAN, enabled=self._color)
        label = colorize(display, Ansi.DIM + Ansi.GRAY, enabled=self._color)
        rendered = f"{_INDENT}{glyph} {label}" if display else f"{_INDENT}{glyph}"

        padding = max(0, self._rendered_width - len(plain))

        self._stream.write("\r" + rendered + (" " * padding))
        self._stream.flush()

        self._rendered_width = len(plain)
        self._frame_index += 1

    def _current_display_message_locked(self) -> str:
        """
        The message this frame should show, before any elapsed-time
        suffix: `self._message` unchanged for a concrete label, or
        the appropriate `_WAITING_ROTATION` phrase once a generic
        waiting label (`self._is_waiting`) has stayed on screen,
        unchanged, for long enough -- see `_WAITING_LABELS`/
        `_WAITING_ROTATION` above.
        """

        if not self._message:
            return ""

        if not self._is_waiting:
            return self._message

        elapsed = time.monotonic() - self._waiting_since
        step = int(elapsed // _ROTATION_INTERVAL_SECONDS)

        if step == 0:
            return self._message

        index = min(step - 1, len(_WAITING_ROTATION) - 1)
        return _WAITING_ROTATION[index]

    def _with_elapsed_suffix_locked(self, message: str) -> str:
        """
        Append `" (Ns)"` once the *whole turn's* elapsed time --
        `self._turn_started_at`, set the moment the in-flight counter
        first left zero -- crosses `_ELAPSED_TIME_THRESHOLD_SECONDS`,
        so a genuinely long-running turn is honest about how long it
        has taken regardless of which label happens to be showing at
        that moment.
        """

        if not message or self._turn_started_at is None:
            return message

        elapsed = time.monotonic() - self._turn_started_at

        if elapsed < _ELAPSED_TIME_THRESHOLD_SECONDS:
            return message

        return f"{message} ({int(elapsed)}s)"

    def _update_title_locked(self, message: str) -> None:
        """
        Mirror `message` (never including the elapsed-time suffix --
        see `_with_elapsed_suffix_locked()`) into the terminal title,
        so the title only ever changes when the visible status
        actually changes, not once per animation frame.
        """

        title = f"{IDLE_TITLE} \u2022 {message}" if message else IDLE_TITLE

        if title == self._title_text:
            return

        self._title_text = title
        set_terminal_title(title)

    def _clear_locked(self) -> None:
        if self._rendered_width:
            self._stream.write("\r" + (" " * self._rendered_width) + "\r")
            self._stream.flush()
            self._rendered_width = 0

    # ------------------------------------------------------------------
    # Shared state transitions
    # ------------------------------------------------------------------

    def _begin(self, message: str) -> None:
        with self._lock:
            if self._active == 0:
                # The very start of a new turn's wait, for the
                # purposes of `_ELAPSED_TIME_THRESHOLD_SECONDS` --
                # deliberately the outermost `*.started` event only,
                # so nested progress (e.g. a child step under
                # `brain.execution`) never resets the clock.
                self._turn_started_at = time.monotonic()

            self._active += 1
            self._set_message_locked(message)

        self._wake_event.set()

    def _update(self, message: str) -> None:
        with self._lock:
            if self._active > 0:
                self._set_message_locked(message)

        self._wake_event.set()

    def _end(self) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)

            if self._active == 0:
                # Cleared synchronously, right here, so the line is
                # already clean by the time this handler returns --
                # regardless of the render thread's own timing -- and
                # in particular by the time `submit_text()` returns
                # to the caller and the final answer/error is printed.
                self._clear_locked()
                self._message = ""
                self._is_waiting = False
                self._turn_started_at = None

                if self._title_text != IDLE_TITLE:
                    self._title_text = IDLE_TITLE
                    set_terminal_title(IDLE_TITLE)

        self._wake_event.set()

    def _set_message_locked(self, message: str) -> None:
        """
        Update the current status message.

        Generic waiting messages share one continuous rotation timeline.
        Switching between generic waiting labels (e.g. "Thinking..." →
        "Working...") does NOT restart the rotation.

        The rotation only restarts when:

        - entering waiting mode from a concrete status, or
        - leaving waiting mode and later entering it again.
        """

        is_waiting = message in _WAITING_LABELS

        # Same waiting phase -> keep rotating from the current position.
        if is_waiting and self._is_waiting:
            self._message = message
            return

        self._message = message
        self._is_waiting = is_waiting

        if is_waiting:
            self._waiting_since = time.monotonic()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_progress_event(self, event: Any) -> None:
        if not isinstance(event, ProgressEvent):
            return

        if event.stage is ProgressStage.STARTED:
            self._begin(_source_label(event.source_id))

        elif event.stage is ProgressStage.PROGRESS:
            self._update(_source_label(event.source_id))

        elif event.stage in (ProgressStage.COMPLETED, ProgressStage.FAILED):
            self._end()

    def _on_capability_started(self, event: Any) -> None:
        if isinstance(event, CapabilityExecutionStartedEvent):
            self._begin(_capability_label(event.capability_id, event.backend))

    def _on_capability_completed(self, event: Any) -> None:
        if isinstance(event, CapabilityExecutionCompletedEvent):
            self._end()

    def _on_capability_failed(self, event: Any) -> None:
        if isinstance(event, CapabilityExecutionFailedEvent):
            self._end()

    def _on_tool_executed(self, event: Any) -> None:
        if isinstance(event, ToolExecuted):
            self._update(_tool_label(event.tool_id))

    def _on_tool_execution_failed(self, event: Any) -> None:
        if isinstance(event, ToolExecutionFailed):
            self._update(_tool_label(event.tool_id))
