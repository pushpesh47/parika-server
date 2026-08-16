"""
PARIKA Interfaces - Formatting

Reusable, presentation-only helpers shared by every Interface for
turning a `ChatTurnResult` or an exception into human-readable text.

Formatting produces plain Markdown-flavored text; converting that text
into a specific presentation (ANSI-colored terminal output, HTML, a
native UI widget, speech) is each concrete Interface's own
responsibility.
"""

from .error_formatter import format_error, format_exception
from .response_formatter import format_chat_turn

__all__ = [
    "format_chat_turn",
    "format_error",
    "format_exception",
]
