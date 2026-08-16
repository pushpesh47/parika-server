"""
PARIKA Lifecycle Exceptions

Defines the exception hierarchy used by LifecycleManager.

These exceptions represent errors encountered while registering
lifecycle hooks and while initializing, starting, stopping,
restarting, or reloading the PARIKA application.

All LifecycleManager-specific exceptions derive from
LifecycleManagerError.
"""

from __future__ import annotations


class LifecycleManagerError(Exception):
    """
    Base exception for all LifecycleManager errors.
    """


class HookAlreadyRegisteredError(LifecycleManagerError):
    """
    Raised when attempting to register a lifecycle hook whose name is
    already registered for the same phase.
    """


class AlreadyInitializedError(LifecycleManagerError):
    """
    Raised when attempting to initialize the application more than
    once.
    """


class NotInitializedError(LifecycleManagerError):
    """
    Raised when an operation requires initialization to have already
    completed.
    """


class InvalidLifecycleTransitionError(LifecycleManagerError):
    """
    Raised when a lifecycle operation is requested while the
    application is not in a state that permits it.
    """


class LifecycleHookError(LifecycleManagerError):
    """
    Raised when one or more lifecycle hooks raise an unhandled
    exception during initialization, startup, or reload.
    """
