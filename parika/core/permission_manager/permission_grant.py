"""
PARIKA Permission Grant

Defines the immutable PermissionGrant record maintained by
PermissionManager.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class PermissionGrant:
    """
    Immutable record authorizing a subject to perform an operation.

    A PermissionGrant represents a static access control entry. It
    does not encode conditional or context-dependent behavior; that
    responsibility belongs to PolicyEngine.
    """

    subject_id: str
    """
    Identifier of the authorized subject (e.g. a Module, Tool, or
    Provider identifier).
    """

    operation: str
    """
    Identifier of the operation the subject is authorized to perform.
    """

    requires_confirmation: bool = False
    """
    Whether performing this operation requires explicit confirmation
    from the user for every check.
    """

    reason: str | None = None
    """
    Optional human-readable explanation of the grant.
    """

    granted_at: datetime = field(
        default_factory=lambda: datetime.now(UTC),
    )
    """
    Timestamp when the grant was created.
    """
