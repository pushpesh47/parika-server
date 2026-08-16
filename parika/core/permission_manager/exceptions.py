"""
PARIKA Permission Manager Exceptions

Defines the exception hierarchy used by PermissionManager.

All PermissionManager-specific exceptions derive from
PermissionManagerError.
"""

from __future__ import annotations


class PermissionManagerError(Exception):
    """
    Base exception for all PermissionManager errors.
    """


class PermissionAlreadyGrantedError(PermissionManagerError):
    """
    Raised when attempting to grant a permission that is already
    granted for the same subject and operation.
    """


class PermissionNotFoundError(PermissionManagerError):
    """
    Raised when a requested PermissionGrant cannot be found.
    """
