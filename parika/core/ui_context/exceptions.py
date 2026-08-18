"""
PARIKA UI Context Exceptions.
"""

from __future__ import annotations


class UIContextError(Exception):
    """Base exception for UI Context errors."""
    pass


class UIContextNotReadyError(UIContextError):
    """Raised when UI Context Projector is not ready."""
    pass


class UIContextProjectionError(UIContextError):
    """Raised when UI context projection fails."""
    pass