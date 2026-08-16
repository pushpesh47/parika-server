"""
PARIKA Console - Tool Footer Rendering

Renders a short, optional line under a chat turn's answer describing
which external tools/capabilities that turn used, and how long the
whole request took -- entirely separate from
`spinner_view.py`/`progress_view.py` (which render *during* execution)
and from `app.py`'s own REPL/layout concerns (which only decide *when*
to call into this module, and own the one timer that measures the
whole request).

This module is a pure View: it reads a chat turn's already-final
`tool_invocations` (the same data `app.py` already had) plus the
overall `succeeded`/`elapsed_seconds` for the request (also computed
by `app.py`, never here), and only changes how that data is
presented. It never calls into Brain, Planner, Providers, or Tools,
and never changes what a turn actually did -- only whether, and how,
that is shown to the user afterwards. In particular, it never sums
any individual tool/capability's own duration: the elapsed time it
renders is always exactly the single, whole-request figure it is
given.

Three modes (`ToolFooterMode`), configured via
`interfaces.cli.tool_footer_mode`:

- `NONE`: never render a footer -- only the answer is shown.
- `SMART` (default): always render a one-line footer -- using
  friendly category names (e.g. "Vision", "Web Search") for whichever
  tools/capabilities were used, never internal capability IDs, tool
  IDs, or provider IDs, or simply "Chat" when none were -- followed
  by the total time the whole request took (e.g. `✓ Used Vision •
  OCR      Total response time: 9s`).
- `DEBUG`: render the previous, fully detailed footer (tool call name
  and per-invocation outcome) unchanged, for developers inspecting
  execution -- still hidden entirely when no tool was used.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum
from typing import Any

from .colors import Ansi, colorize

_SUCCESS_MARK = "\u2713"  # ✓
_FAILURE_MARK = "\u2717"  # ✗

"""
The `SMART`-mode label for a turn that used no tool/capability at
all -- the model simply answered directly -- so the footer still has
something to say "Used" before the total response time, instead of
either hiding the footer or leaving that half of the line empty.
"""


class ToolFooterMode(Enum):
    """
    Which of the three tool-footer rendering modes is active. Purely a
    presentation choice: has no effect on execution, and the same
    `tool_invocations` data is available regardless of which mode is
    selected.
    """

    NONE = "none"
    SMART = "smart"
    DEBUG = "debug"

    @classmethod
    def from_value(cls, value: object) -> "ToolFooterMode":
        """
        Parse a configuration value (e.g. from
        `interfaces.cli.tool_footer_mode`) into a `ToolFooterMode`,
        falling back to `SMART` -- the documented default -- for any
        missing or unrecognized value, so a typo in configuration
        degrades gracefully instead of crashing the Console.
        """

        if value is None:
            return cls.SMART

        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return cls.SMART


_FRIENDLY_CATEGORY_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("vision", "Vision"),
    ("ocr", "OCR"),
    ("weather", "Weather"),
    ("web", "Web Search"),
    ("filesystem", "Filesystem"),
    ("repository", "Filesystem"),
    ("calculator", "Calculator"),
    ("calc", "Calculator"),
    ("python", "Python"),
    ("shell", "Shell"),
    ("git", "Git"),
    ("database", "Database"),
    ("db", "Database"),
    ("coding", "Code"),
)
"""
Best-effort, keyword-based mapping from an internal identifier (a
capability ID, or a tool call name, whichever is available) to the
short, friendly category name `SMART` mode shows the end user --
mirroring `spinner_view.py`'s own keyword-fallback philosophy, so a
present or future tool with no entry here still renders a sensible,
non-technical name instead of exposing its raw identifier.
"""


def _friendly_category_name(identifier: str) -> str:
    lowered = identifier.lower()

    for keyword, name in _FRIENDLY_CATEGORY_KEYWORDS:
        if keyword in lowered:
            return name

    leading_segment = identifier.split(".")[0].replace("_", " ").strip()

    return leading_segment.title() or identifier


def _invocation_identifier(invocation: Any) -> str:
    # Prefer the internal capability ID (the more stable, canonical
    # identifier) when available, falling back to the tool call name
    # the model itself used -- either way, only ever used here to
    # look up a friendly category name, never shown to the user as-is.
    return (
        getattr(invocation, "capability_id", None)
        or invocation.name
    )


def render_tool_footer(
    invocations: Sequence[Any],
    *,
    mode: ToolFooterMode,
    color: bool,
    succeeded: bool,
    elapsed_seconds: float,
) -> str | None:
    """
    Render the tool footer for one chat turn, or return `None` when
    nothing should be shown -- because `mode` is `ToolFooterMode.NONE`,
    or (in `DEBUG` mode only) because the turn used no tool at all.

    `SMART` mode always renders, even for a turn that used no tool at
    all (labelled "Chat"), since every turn -- tool-using or not,
    successful or not -- now also reports the total time the whole
    request took via `succeeded`/`elapsed_seconds`, which describe the
    *entire* request, never any one tool/capability/provider within
    it.
    """

    if mode is ToolFooterMode.NONE:
        return None

    if mode is ToolFooterMode.DEBUG:
        if not invocations:
            return None

        return _render_debug_footer(invocations, color=color)

    return _render_smart_footer(
        invocations,
        color=color,
        succeeded=succeeded,
        elapsed_seconds=elapsed_seconds,
    )


def _render_debug_footer(invocations: Sequence[Any], *, color: bool) -> str:
    """
    The detailed, developer-facing footer: every invocation's own
    call name and outcome, unchanged from before Tool Footer Modes
    were introduced.
    """

    parts = [
        f"{invocation.name} "
        f"{_SUCCESS_MARK if invocation.succeeded else _FAILURE_MARK}"
        for invocation in invocations
    ]

    return colorize(
        "  \u21b3 " + " \u00b7 ".join(parts), Ansi.DIM, enabled=color
    )


def _render_smart_footer(
    invocations: Sequence[Any],
    *,
    color: bool,
    succeeded: bool,
    elapsed_seconds: float,
) -> str:
    """
    The default, user-facing footer: a deduplicated list of friendly
    category names (e.g. "Vision", "Web Search"), never an internal
    capability ID, tool ID, or provider ID, followed by the total
    time the whole request took.

    If no tool/capability was used, no "Used ..." section is shown;
    only the total response time is displayed.
    """

    names: list[str] = []

    for invocation in invocations:
        name = _friendly_category_name(_invocation_identifier(invocation))

        if name not in names:
            names.append(name)

    mark = _SUCCESS_MARK if succeeded else _FAILURE_MARK
    duration = format_duration(elapsed_seconds)

    if names:
        text = (
            f"{mark} Used {' • '.join(names)}"
            f"      Response time: {duration}"
        )
    else:
        text = f"{mark} Response time: {duration}"

    return colorize(text, Ansi.DIM, enabled=color)


def format_duration(seconds: float) -> str:
    """
    Format a total elapsed duration for the tool footer's "Total
    response time", concise and human-readable: whole seconds only
    (never milliseconds or decimals, e.g. never `"72.153s"`), and,
    once a minute has elapsed, an `Nm SSs` form with the seconds
    component zero-padded (e.g. `"1m 02s"`, never raw seconds like
    `"72 seconds"`).
    """

    total_seconds = max(0, round(seconds))
    minutes, secs = divmod(total_seconds, 60)

    if minutes:
        return f"{minutes}m {secs:02d}s"

    return f"{secs}s"
