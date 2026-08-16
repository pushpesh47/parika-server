"""
PARIKA Permission Manager - Workspace Permission Scope

Defines the four choices a user may make when
`WorkspacePermissionManager` asks for permission to access a workspace
outside the trusted set.
"""

from __future__ import annotations

from enum import StrEnum


class WorkspacePermissionScope(StrEnum):
    """
    The lifetime a granted (or denied) workspace permission applies for.
    """

    ONCE = "once"
    """Authorizes only the current call; nothing is stored."""

    SESSION = "session"
    """
    Authorizes every future call for the same workspace and operation
    for the remainder of the current process (today, one CLI
    process/`InterfaceSession` - see
    `docs/architecture/Core_Component_Responsibilities.md` section 25).
    """

    PERMANENT = "permanent"
    """
    Same effect as `SESSION` for the current process, plus persists the
    workspace into `trusted_workspaces` (`config/runtime.toml`) so it
    survives a restart.
    """

    DENY = "deny"
    """Rejects only the current call; nothing is stored."""
