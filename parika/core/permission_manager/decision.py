"""
PARIKA Permission Decision

Defines the immutable PermissionDecision produced by
PermissionManager.check().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class PermissionDecision:
    """
    Immutable result of an authorization check.
    """

    subject_id: str
    """
    Identifier of the subject that was checked.
    """

    operation: str
    """
    Identifier of the operation that was checked.
    """

    authorized: bool
    """
    Whether the operation is authorized to proceed immediately.
    """

    requires_confirmation: bool
    """
    Whether the operation requires explicit user confirmation before
    it may proceed.
    """

    reason: str | None = None
    """
    Optional human-readable explanation of the decision.
    """

    evaluated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC),
    )
    """
    Timestamp when the decision was produced.
    """
