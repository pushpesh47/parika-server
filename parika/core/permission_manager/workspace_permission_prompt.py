"""
PARIKA Permission Manager - Workspace Permission Prompt Protocol

Defines the narrow, structurally-typed contract
`WorkspacePermissionManager` depends on to interactively ask a user for
a permission decision.

This Protocol is owned by the `permission_manager` package itself -
exactly like `ExperienceSource` is owned by Planner's package (see
`parika/core/planner/model_selection/experience_source.py`) - so
`WorkspacePermissionManager` never imports a concrete Interface
implementation. The concrete implementation (e.g. a Console prompt
that reads a line from stdin) lives in the native Console
(`parika/console/`) and is injected at the composition root
(`parika/interfaces/runtime.py`). Core therefore still never depends on
a concrete Interface/Console - it only depends on the abstraction it
itself defines.

When no `WorkspacePermissionPrompt` is injected (`prompt=None`),
`WorkspacePermissionManager` fails closed (treats the request as
`WorkspacePermissionScope.DENY`) rather than blocking indefinitely -
see `docs/architecture/Core_Component_Responsibilities.md` section 25.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from .workspace_operation import WorkspaceOperation
from .workspace_permission_scope import WorkspacePermissionScope


@runtime_checkable
class WorkspacePermissionPrompt(Protocol):
    """
    Structural contract for interactively requesting a workspace
    permission decision from a user.
    """

    def request_decision(
        self,
        *,
        workspace: Path,
        operation: WorkspaceOperation,
        reason: str | None,
    ) -> WorkspacePermissionScope:
        """
        Ask the user to choose a permission scope for one workspace and
        operation.

        Args:
            workspace:
                The resolved workspace directory requiring a decision.

            operation:
                The operation being requested (`WRITE`, `DELETE`, or
                `EXECUTE` - `READ` is never checked through this
                extension).

            reason:
                Optional human-readable context for the request (e.g.
                the argument name or command that triggered it).

        Returns:
            The scope the user chose (`ONCE`, `SESSION`, `PERMANENT`,
            or `DENY`).
        """
