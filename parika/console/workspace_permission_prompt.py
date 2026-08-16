"""
PARIKA Console - Workspace Permission Prompt

Implements `WorkspacePermissionPrompt`
(`parika.core.permission_manager.workspace_permission_prompt`) for the
Console: a synchronous, four-choice `input()` prompt.

This is the concrete implementation of the Core-defined Protocol -
Core (`WorkspacePermissionManager`) never imports this class; it is
constructed and injected at the composition root
(`parika/interfaces/runtime.py`), the same dependency-inversion shape
already used for `ExperienceSource`. A CLI process hosts exactly one
`InterfaceSession` for its whole lifetime today (see
`docs/architecture/Core_Component_Responsibilities.md` section 25), so
one `CliWorkspacePermissionPrompt` instance per process is all that is
needed.

If stdin is closed or interrupted mid-prompt, the request is treated
as `DENY` rather than raising - the same fail-safe posture
`WorkspacePermissionManager` itself applies when no prompt is
registered at all.
"""

from __future__ import annotations

from pathlib import Path

from parika.core.permission_manager.workspace_operation import WorkspaceOperation
from parika.core.permission_manager.workspace_permission_scope import (
    WorkspacePermissionScope,
)

_CHOICES: dict[str, WorkspacePermissionScope] = {
    "1": WorkspacePermissionScope.ONCE,
    "2": WorkspacePermissionScope.SESSION,
    "3": WorkspacePermissionScope.PERMANENT,
    "4": WorkspacePermissionScope.DENY,
}


class CliWorkspacePermissionPrompt:
    """
    Renders the four-choice permission prompt on the CLI and reads the
    user's choice from stdin.
    """

    def request_decision(
        self,
        *,
        workspace: Path,
        operation: WorkspaceOperation,
        reason: str | None,
    ) -> WorkspacePermissionScope:
        """
        Ask the user, via stdin/stdout, which scope to apply.

        See `WorkspacePermissionPrompt.request_decision()` for the
        full contract.
        """

        print()
        print("PARIKA requires permission.")
        print(f"Workspace: {workspace}")
        print(f"Operation: {operation.value}")

        if reason:
            print(f"Reason: {reason}")

        print("  [1] Allow once")
        print("  [2] Allow for this session")
        print("  [3] Always trust this workspace")
        print("  [4] Deny")

        try:
            while True:
                choice = input("> ").strip()

                if not choice:
                    return WorkspacePermissionScope.DENY

                scope = _CHOICES.get(choice)

                if scope is not None:
                    return scope

                print("Please enter 1, 2, 3, or 4.")

        except (EOFError, KeyboardInterrupt):
            print()
            return WorkspacePermissionScope.DENY
