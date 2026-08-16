"""
PARIKA Interfaces - Error Formatting

Turns exceptions into short, human-readable text suitable for direct
display by any Interface.
"""

from __future__ import annotations


def format_error(message: str) -> str:
    """
    Format a plain error message for display.
    """

    return f"Error: {message}"


def format_exception(exception: BaseException) -> str:
    """
    Format an exception for display.

    Includes the exception's type name so users (and support
    requests) can distinguish, for example, a capability-not-found
    error from a network failure without needing a stack trace.
    """

    return f"Error ({type(exception).__name__}): {exception}"
