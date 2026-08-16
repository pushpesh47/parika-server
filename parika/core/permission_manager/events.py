"""
PARIKA Permission Manager Events

Defines the immutable events published by PermissionManager.

Events are immutable data containers and carry no business logic.
"""

from __future__ import annotations

from dataclasses import dataclass

from .permission_grant import PermissionGrant


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionGrantedEvent:
    """Published after a permission has been granted."""

    grant: PermissionGrant
    """The newly created PermissionGrant."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionRevokedEvent:
    """Published after a permission has been revoked."""

    subject_id: str
    """Identifier of the subject whose grant was revoked."""

    operation: str
    """Identifier of the revoked operation."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PermissionDeniedEvent:
    """Published when an authorization check is denied."""

    subject_id: str
    """Identifier of the subject that was denied."""

    operation: str
    """Identifier of the denied operation."""

    reason: str | None
    """Optional human-readable explanation of the denial."""
