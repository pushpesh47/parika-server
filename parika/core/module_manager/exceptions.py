"""
PARIKA Module Manager Exceptions

Defines the exception hierarchy used by the ModuleManager.

These exceptions represent ModuleManager-specific error conditions.
They are descriptive only and contain no business logic.
"""

from __future__ import annotations


class ModuleManagerError(Exception):
    """
    Base exception for all ModuleManager errors.
    """


class ModuleAlreadyRegisteredError(ModuleManagerError):
    """
    Raised when attempting to register a Module that already exists.
    """


class ModuleNotFoundError(ModuleManagerError):
    """
    Raised when a requested Module cannot be found.
    """


class ModuleAlreadyLoadedError(ModuleManagerError):
    """
    Raised when attempting to load a Module that is already active.
    """


class ModuleNotLoadedError(ModuleManagerError):
    """
    Raised when attempting to unload a Module that is not active.
    """


class ModuleLoadError(ModuleManagerError):
    """
    Raised when a Module fails to start successfully.
    """


class ModuleUnloadError(ModuleManagerError):
    """
    Raised when a Module fails to stop successfully.
    """


class DriverNotFoundError(ModuleManagerError):
    """
    Raised when the configured ModuleDriver cannot be located.
    """