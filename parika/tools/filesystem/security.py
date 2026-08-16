"""
PARIKA Filesystem Tool - Path Security

Confines mutating and destructive filesystem operations to a trusted
set of workspaces, and gates them behind their own configuration flags
(`allow_write`, `allow_delete`).

This is the single choke point every operation in `driver.py` must
pass a path through before touching the real filesystem. No other
module in this Tool ever resolves or validates a path itself.

Security posture, per the System Interaction Foundation's workspace
access model (see `docs/development/Tool_Guide.md` section 23.1):

- Reads (`resolve(..., enforce_roots=False)`) are always allowed, any
  resolvable host path, unconditionally - PARIKA may read any file on
  the operating system. There is no configuration that disables this.
- Mutating/destructive operations (`resolve(..., enforce_roots=True)`,
  the default) remain confined. When a `WorkspacePermissionManager` is
  injected (`permissions=`), authorization for a path outside
  `allowed_roots` is delegated to it entirely - `PathSecurity` never
  makes its own competing trust decision in that case, keeping
  permission enforcement centralized in one place. When no
  `WorkspacePermissionManager` is injected, `PathSecurity` falls back
  to its original, self-contained allow-list behavior (hard deny
  outside `allowed_roots`, deny-by-default when none are configured)
  for full backward compatibility with callers that do not opt into
  the shared Workspace Permission Manager.

A relative path is resolved against the first configured root, or
against the current working directory when none are configured.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from parika.core.permission_manager.workspace_operation import WorkspaceOperation

from .exceptions import (
    FilesystemOperationNotPermittedError,
    InvalidFilesystemArgumentError,
    PathNotAllowedError,
)

if TYPE_CHECKING:
    from parika.core.permission_manager.workspace_permission_manager import (
        WorkspacePermissionManager,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class PathSecurityConfig:
    """
    Immutable configuration controlling `PathSecurity`'s behavior.
    """

    allowed_roots: tuple[Path, ...] = field(default_factory=tuple)
    """
    Every directory filesystem operations may touch, and any path
    beneath it (after resolving symlinks and `..` segments). Empty by
    default - deny-by-default, matching the security posture required
    for a tool with direct filesystem access.
    """

    allow_write: bool = True
    """Whether `write`, `mkdir`, `copy`, and `move` are permitted."""

    allow_delete: bool = False
    """Whether `delete` is permitted."""


class PathSecurity:
    """
    Resolves and validates paths against a configured allowlist of
    root directories.
    """

    def __init__(
        self,
        config: PathSecurityConfig,
        *,
        permissions: "WorkspacePermissionManager | None" = None,
    ) -> None:
        """
        Initialize the path security boundary.

        Args:
            config:
                Immutable security configuration.

            permissions:
                Optional shared `WorkspacePermissionManager`. When
                supplied, authorization for a mutating/destructive
                path outside `allowed_roots` is delegated to it
                entirely - no separate, duplicate trust decision is
                made here. When omitted (`None`), `PathSecurity` falls
                back to its original, self-contained allow-list
                behavior for full backward compatibility.
        """

        self._roots = tuple(root.resolve() for root in config.allowed_roots)
        self.allow_write = config.allow_write
        self.allow_delete = config.allow_delete
        self._permissions = permissions

    @property
    def allowed_roots(self) -> tuple[Path, ...]:
        """
        Every resolved root directory this boundary confines
        operations to.
        """

        return self._roots

    def resolve(
        self,
        raw_path: object,
        *,
        argument_name: str = "path",
        enforce_roots: bool = True,
        operation: WorkspaceOperation | None = None,
    ) -> Path:
        """
        Resolve and validate a caller-supplied path string.

        Args:
            raw_path:
                The raw value supplied in `ToolRequest.arguments`.
                Must be a non-empty string.

            argument_name:
                Name of the argument, used only for error messages and
                as the `reason` surfaced to an interactive permission
                prompt, if one is shown.

            enforce_roots:
                When True (the default - always used for mutating
                operations: `write`, `copy` destination, `move`,
                `delete`, `mkdir`), the resolved path must be
                authorized (see below). When False (used only by
                read-only operations: `read`, `list`, `search`,
                `walk`, `info`, `permissions`, `exists`, `watch`, and
                `copy`/`move`'s source), any resolvable path on the
                host filesystem is permitted, unconditionally - PARIKA
                may read any file on the operating system.

            operation:
                The `WorkspaceOperation` this call represents (`WRITE`
                or `DELETE`), passed through to
                `WorkspacePermissionManager.check()` when one is
                injected. Defaults to `WRITE` when omitted. Ignored
                when `enforce_roots` is False.

        Returns:
            The fully resolved, absolute `Path`.

        Raises:
            InvalidFilesystemArgumentError:
                If `raw_path` is not a non-empty string.

            PathNotAllowedError:
                When `enforce_roots` is True and the resolved path is
                not authorized - either because a
                `WorkspacePermissionManager` denied it, or (with none
                injected) because it falls outside every configured
                `allowed_roots` entry, or none are configured at all.
        """

        if not isinstance(raw_path, str) or not raw_path.strip():
            raise InvalidFilesystemArgumentError(
                f"request.arguments['{argument_name}'] must be a "
                "non-empty string."
            )

        candidate = Path(raw_path)

        if not candidate.is_absolute():
            anchor = self._roots[0] if self._roots else Path.cwd()
            candidate = anchor / candidate

        resolved = candidate.resolve()

        if not enforce_roots:
            return resolved

        if self._permissions is not None:
            decision = self._permissions.check(
                resolved,
                operation if operation is not None else WorkspaceOperation.WRITE,
                reason=argument_name,
            )

            if decision.authorized:
                return resolved

            raise PathNotAllowedError(
                f"Path '{raw_path}' resolves to '{resolved}', which is "
                "outside every trusted workspace and was not authorized."
            )

        if not self._roots:
            raise PathNotAllowedError(
                "Filesystem access is disabled: no `[filesystem]."
                "allowed_roots` are configured."
            )

        for root in self._roots:
            if resolved == root or root in resolved.parents:
                return resolved

        raise PathNotAllowedError(
            f"Path '{raw_path}' resolves to '{resolved}', which is "
            "outside every configured `[filesystem].allowed_roots` "
            f"entry ({', '.join(str(root) for root in self._roots)})."
        )

    def require_write(self) -> None:
        """
        Raise `FilesystemOperationNotPermittedError` unless writing is
        enabled by configuration.
        """

        if not self.allow_write:
            raise FilesystemOperationNotPermittedError(
                "Write operations are disabled by configuration "
                "(`[filesystem].allow_write = false`)."
            )

    def require_delete(self) -> None:
        """
        Raise `FilesystemOperationNotPermittedError` unless deletion
        is enabled by configuration.
        """

        if not self.allow_delete:
            raise FilesystemOperationNotPermittedError(
                "Delete operations are disabled by configuration "
                "(`[filesystem].allow_delete = false`)."
            )
