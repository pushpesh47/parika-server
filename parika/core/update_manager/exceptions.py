"""
PARIKA Update Manager Exceptions

Defines the exception hierarchy used by UpdateManager.

All UpdateManager-specific exceptions derive from UpdateManagerError.
"""

from __future__ import annotations


class UpdateManagerError(Exception):
    """
    Base exception for all UpdateManager errors.
    """


class TargetAlreadyRegisteredError(UpdateManagerError):
    """
    Raised when attempting to register a target whose identifier is
    already registered.
    """


class InvalidUpdateTargetError(UpdateManagerError):
    """
    Raised when a target registration is structurally invalid, such
    as a non-callable check or apply callable.
    """


class TargetNotFoundError(UpdateManagerError):
    """
    Raised when a requested update target is not registered.
    """


class UpdateNotAvailableError(UpdateManagerError):
    """
    Raised when attempting to apply an update for a target that has
    no pending update.
    """


class UpdateApplyError(UpdateManagerError):
    """
    Raised when a target's apply callable raises an unhandled
    exception.
    """


class MigrationAlreadyRegisteredError(UpdateManagerError):
    """
    Raised when attempting to register a configuration migration
    whose version is already registered.
    """


class MigrationError(UpdateManagerError):
    """
    Raised when a configuration migration callable raises an
    unhandled exception.
    """
