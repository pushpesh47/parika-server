"""
PARIKA Health Manager Exceptions

Defines the exception hierarchy used by HealthManager.

All HealthManager-specific exceptions derive from HealthManagerError.
"""

from __future__ import annotations


class HealthManagerError(Exception):
    """
    Base exception for all HealthManager errors.
    """


class ComponentAlreadyRegisteredError(HealthManagerError):
    """
    Raised when attempting to register a component that is already
    registered.
    """


class ComponentNotFoundError(HealthManagerError):
    """
    Raised when a requested component is not registered.
    """


class InvalidHealthCheckError(HealthManagerError):
    """
    Raised when a supplied health check callable is invalid.
    """
