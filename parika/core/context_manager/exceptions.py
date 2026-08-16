"""
PARIKA ContextManager Exceptions

Defines the exception hierarchy used by the ContextManager.
"""

from __future__ import annotations


class ContextManagerError(Exception):
    """
    Base exception for all ContextManager errors.
    """


class ContextAlreadyExistsError(ContextManagerError):
    """
    Raised when attempting to register a Context whose identifier is
    already present in the ContextManager.
    """


class ContextNotFoundError(ContextManagerError):
    """
    Raised when the requested Context cannot be found.
    """


class InvalidContextError(ContextManagerError):
    """
    Raised when an invalid Context object is supplied to the
    ContextManager.
    """