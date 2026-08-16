"""
PARIKA Console - Terminal Colors

Small ANSI escape-code helpers used by the CLI's markdown renderer and
application loop. No third-party terminal-color dependency is
introduced, in keeping with the project's standard-library-first
preference.
"""

from __future__ import annotations


class Ansi:
    """
    ANSI SGR escape codes used by the CLI.
    """

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"

    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    GRAY = "\033[90m"
    BRIGHT_CYAN = "\033[96m"


def colorize(text: str, code: str, *, enabled: bool = True) -> str:
    """
    Wrap `text` with an ANSI escape code, or return it unchanged.

    Args:
        text:
            Text to colorize.

        code:
            One or more concatenated `Ansi` escape codes.

        enabled:
            Whether coloring is enabled. Callers should pass False
            when output is not a TTY or the user has disabled color.
    """

    if not enabled or not code or not text:
        return text

    return f"{code}{text}{Ansi.RESET}"
