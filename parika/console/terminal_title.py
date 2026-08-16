"""
PARIKA Console - Terminal Title

Updates the terminal emulator's window/tab title via the standard OSC
`Set Window Title` escape sequence, so the title reflects, at a
glance, whether PARIKA is idle or actively working and roughly what it
is doing -- without adding any visible line of its own to the
conversation.

Purely a presentation nicety, entirely owned by the Console layer:
nothing here calls into, or is called by, Brain/Planner/Tools/
Providers, and it never affects what is rendered in the terminal body,
only the surrounding window/tab chrome.

Always targets the real `sys.stdout` (the actual terminal), regardless
of whatever separately redirectable stream a renderer such as
`spinner_view.SpinnerProgressRenderer` was constructed with for its
own line-based output -- so redirecting or capturing that stream (as
tests do) never triggers a title escape sequence, and a real terminal
always gets one. Guarded by `isatty()` for the same reason: writing an
escape sequence into redirected/piped/captured output would otherwise
leak an invisible-but-real artifact into whatever consumes it.
"""

from __future__ import annotations

import sys

IDLE_TITLE = "PARIKA"
"""The title shown whenever nothing is in flight."""

_OSC_SET_TITLE = "\033]0;{title}\007"
"""OSC 0 (set icon name and window title), terminated with BEL --
understood by every common terminal emulator."""


def set_terminal_title(title: str) -> None:
    """
    Set the terminal title, if standard output is an actual terminal.

    A no-op whenever standard output is not a TTY (e.g. redirected,
    piped, or captured by tests), so nothing here ever leaks an escape
    sequence into non-terminal output.
    """

    stream = sys.stdout

    try:
        is_tty = stream.isatty()
    except (AttributeError, ValueError):  # pragma: no cover - defensive
        is_tty = False

    if not is_tty:
        return

    stream.write(_OSC_SET_TITLE.format(title=title))
    stream.flush()


def reset_terminal_title() -> None:
    """Restore the idle title (`PARIKA`). See `set_terminal_title()`."""

    set_terminal_title(IDLE_TITLE)
