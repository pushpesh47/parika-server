"""
PARIKA Interfaces - Errors

Defines the exception hierarchy used by the Interface layer.

These exceptions describe Interface-level error conditions only
(malformed commands, session misuse); they are never raised in place
of a `BrainResponse` failure, which is always reported through the
response itself rather than an exception (see
`parika.core.brain.brain_response.BrainResponse`).
"""

from __future__ import annotations


class InterfaceError(Exception):
    """
    Base exception for all Interface-layer errors.
    """


class UnknownCommandError(InterfaceError):
    """
    Raised when a slash command does not match any registered
    command.
    """


class CommandExecutionError(InterfaceError):
    """
    Raised when a slash command fails while executing.
    """
