"""
PARIKA Runtime Info Tool Exceptions

Defines the exception hierarchy used by the Runtime Info Tool.

All Runtime Info Tool exceptions derive from `RuntimeInfoToolError` so
that `ToolManager` can uniformly wrap them as `ToolExecutionError`.
"""

from __future__ import annotations


class RuntimeInfoToolError(Exception):
    """
    Base exception for all Runtime Info Tool errors.
    """


class UnknownTimezoneError(RuntimeInfoToolError):
    """
    Raised when a requested timezone name or abbreviation cannot be
    resolved.
    """
