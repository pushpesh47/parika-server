"""
PARIKA Permission Manager - Workspace Permission Events

Defines the immutable events published by `WorkspacePermissionManager`.

Events are immutable data containers and carry no business logic. They
compose with, and do not replace, the existing `permission.granted` /
`permission.revoked` / `permission.denied` events already published by
the underlying `PermissionManager.grant()`/`revoke()`/`check()` calls
`WorkspacePermissionManager` makes on their behalf.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .workspace_permission_decision import WorkspacePermissionDecision


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkspacePermissionEvaluatedEvent:
    """Published after every `WorkspacePermissionManager.check()` call."""

    decision: WorkspacePermissionDecision
    """The resolved decision."""


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkspaceTrustedEvent:
    """Published after a workspace is marked `PERMANENT`ly trusted."""

    workspace: Path
    """The workspace that was added to `trusted_workspaces`."""
