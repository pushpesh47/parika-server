"""
PARIKA Permission Manager - Workspace Operation

Defines the fixed set of workspace-scoped operations the Workspace
Permission Manager extension authorizes (see `workspace_permission_manager.py`).
"""

from __future__ import annotations

from enum import StrEnum


class WorkspaceOperation(StrEnum):
    """
    Workspace-scoped operation kinds authorized by
    `WorkspacePermissionManager`.

    `READ` is defined for completeness and possible future reuse by
    another component; the Filesystem Tool never checks it through
    this extension - reading, searching, and inspecting files is
    always allowed on any host path, independent of workspace trust
    (see `docs/development/Tool_Guide.md` section 23.1).
    """

    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    EXECUTE = "execute"
