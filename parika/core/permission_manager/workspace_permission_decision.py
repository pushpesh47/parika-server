"""
PARIKA Permission Manager - Workspace Permission Decision

Defines the immutable result produced by
`WorkspacePermissionManager.check()`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .workspace_operation import WorkspaceOperation
from .workspace_permission_scope import WorkspacePermissionScope


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkspacePermissionDecision:
    """
    Immutable result of a workspace-scoped authorization check.
    """

    workspace: Path
    """The resolved workspace directory that was checked."""

    operation: WorkspaceOperation
    """The operation that was checked."""

    authorized: bool
    """Whether the operation is authorized to proceed."""

    scope_applied: WorkspacePermissionScope | None = None
    """
    The scope that produced this decision, when one was resolved
    through a prompt (`None` for the trusted-workspace fast path, where
    no scope choice was ever needed).
    """

    reason: str | None = None
    """Optional human-readable explanation of the decision."""

    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    """Timestamp when the decision was produced."""
