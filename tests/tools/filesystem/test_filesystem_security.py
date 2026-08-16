"""
Unit tests for PathSecurity.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parika.core.permission_manager.workspace_operation import WorkspaceOperation
from parika.core.permission_manager.workspace_permission_decision import (
    WorkspacePermissionDecision,
)
from parika.tools.filesystem.exceptions import (
    FilesystemOperationNotPermittedError,
    InvalidFilesystemArgumentError,
    PathNotAllowedError,
)
from parika.tools.filesystem.security import PathSecurity, PathSecurityConfig


class _FakeWorkspacePermissionManager:
    """
    Minimal stand-in satisfying the one method `PathSecurity` calls,
    so these unit tests can assert the delegation contract without
    constructing a real `WorkspacePermissionManager`.
    """

    def __init__(self, *, authorized: bool) -> None:
        self.authorized = authorized
        self.calls: list[tuple[Path, WorkspaceOperation, str | None]] = []

    def check(
        self,
        path: Path,
        operation: WorkspaceOperation,
        *,
        reason: str | None = None,
    ) -> WorkspacePermissionDecision:
        self.calls.append((path, operation, reason))

        return WorkspacePermissionDecision(
            workspace=path,
            operation=operation,
            authorized=self.authorized,
        )


class TestResolve:
    def test_rejects_non_string(self, tmp_path: Path) -> None:
        security = PathSecurity(
            PathSecurityConfig(allowed_roots=(tmp_path,))
        )

        with pytest.raises(InvalidFilesystemArgumentError):
            security.resolve(123)

    def test_rejects_empty_string(self, tmp_path: Path) -> None:
        security = PathSecurity(
            PathSecurityConfig(allowed_roots=(tmp_path,))
        )

        with pytest.raises(InvalidFilesystemArgumentError):
            security.resolve("   ")

    def test_no_allowed_roots_denies_everything(self, tmp_path: Path) -> None:
        security = PathSecurity(PathSecurityConfig(allowed_roots=()))

        with pytest.raises(PathNotAllowedError):
            security.resolve(str(tmp_path / "a.txt"))

    def test_path_inside_root_is_allowed(self, tmp_path: Path) -> None:
        security = PathSecurity(
            PathSecurityConfig(allowed_roots=(tmp_path,))
        )

        resolved = security.resolve(str(tmp_path / "sub" / "a.txt"))

        assert resolved == (tmp_path / "sub" / "a.txt").resolve()

    def test_path_outside_root_is_denied(self, tmp_path: Path) -> None:
        security = PathSecurity(
            PathSecurityConfig(allowed_roots=(tmp_path,))
        )

        with pytest.raises(PathNotAllowedError):
            security.resolve("/etc/passwd")

    def test_traversal_outside_root_is_denied(self, tmp_path: Path) -> None:
        security = PathSecurity(
            PathSecurityConfig(allowed_roots=(tmp_path,))
        )

        with pytest.raises(PathNotAllowedError):
            security.resolve(str(tmp_path / ".." / "escaped.txt"))

    def test_relative_path_resolves_against_first_root(
        self, tmp_path: Path
    ) -> None:
        security = PathSecurity(
            PathSecurityConfig(allowed_roots=(tmp_path,))
        )

        resolved = security.resolve("note.txt")

        assert resolved == (tmp_path / "note.txt").resolve()

    def test_symlink_escaping_root_is_denied(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / "outside_target.txt"
        outside.write_text("secret")

        allowed_root = tmp_path / "allowed"
        allowed_root.mkdir()
        link = allowed_root / "escape_link"

        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not supported in this environment")

        security = PathSecurity(
            PathSecurityConfig(allowed_roots=(allowed_root,))
        )

        with pytest.raises(PathNotAllowedError):
            security.resolve(str(link))

        outside.unlink()

    def test_root_itself_is_allowed(self, tmp_path: Path) -> None:
        security = PathSecurity(
            PathSecurityConfig(allowed_roots=(tmp_path,))
        )

        assert security.resolve(str(tmp_path)) == tmp_path.resolve()


class TestPermissionGates:
    def test_require_write_raises_when_disabled(self, tmp_path: Path) -> None:
        security = PathSecurity(
            PathSecurityConfig(allowed_roots=(tmp_path,), allow_write=False)
        )

        with pytest.raises(FilesystemOperationNotPermittedError):
            security.require_write()

    def test_require_write_passes_when_enabled(self, tmp_path: Path) -> None:
        security = PathSecurity(
            PathSecurityConfig(allowed_roots=(tmp_path,), allow_write=True)
        )

        security.require_write()

    def test_require_delete_raises_when_disabled(self, tmp_path: Path) -> None:
        security = PathSecurity(
            PathSecurityConfig(allowed_roots=(tmp_path,), allow_delete=False)
        )

        with pytest.raises(FilesystemOperationNotPermittedError):
            security.require_delete()

    def test_require_delete_passes_when_enabled(self, tmp_path: Path) -> None:
        security = PathSecurity(
            PathSecurityConfig(allowed_roots=(tmp_path,), allow_delete=True)
        )

        security.require_delete()


class TestWorkspacePermissionManagerDelegation:
    """
    When a `WorkspacePermissionManager` is injected, it is the sole
    authority for mutating/destructive paths outside `allowed_roots` -
    `PathSecurity` never makes a second, competing trust decision.
    """

    def test_authorized_decision_allows_the_path(self, tmp_path: Path) -> None:
        permissions = _FakeWorkspacePermissionManager(authorized=True)
        security = PathSecurity(
            PathSecurityConfig(allowed_roots=()), permissions=permissions
        )
        outside = tmp_path / "outside" / "a.txt"

        resolved = security.resolve(
            str(outside), operation=WorkspaceOperation.WRITE
        )

        assert resolved == outside.resolve()
        assert permissions.calls == [
            (outside.resolve(), WorkspaceOperation.WRITE, "path")
        ]

    def test_denied_decision_raises_path_not_allowed(self, tmp_path: Path) -> None:
        permissions = _FakeWorkspacePermissionManager(authorized=False)
        security = PathSecurity(
            PathSecurityConfig(allowed_roots=()), permissions=permissions
        )

        with pytest.raises(PathNotAllowedError):
            security.resolve(
                str(tmp_path / "a.txt"), operation=WorkspaceOperation.DELETE
            )

    def test_defaults_operation_to_write_when_omitted(self, tmp_path: Path) -> None:
        permissions = _FakeWorkspacePermissionManager(authorized=True)
        security = PathSecurity(
            PathSecurityConfig(allowed_roots=()), permissions=permissions
        )

        security.resolve(str(tmp_path / "a.txt"))

        assert permissions.calls[0][1] is WorkspaceOperation.WRITE

    def test_reads_never_consult_the_permission_manager(
        self, tmp_path: Path
    ) -> None:
        permissions = _FakeWorkspacePermissionManager(authorized=False)
        security = PathSecurity(
            PathSecurityConfig(allowed_roots=()), permissions=permissions
        )

        resolved = security.resolve(
            str(tmp_path / "a.txt"), enforce_roots=False
        )

        assert resolved == (tmp_path / "a.txt").resolve()
        assert permissions.calls == []

    def test_permission_manager_bypasses_local_allowed_roots_entirely(
        self, tmp_path: Path
    ) -> None:
        """
        Even a path that WOULD satisfy the local `allowed_roots` check
        is routed entirely through the injected
        `WorkspacePermissionManager` - there is exactly one place that
        decides authorization once one is injected, never two.
        """

        permissions = _FakeWorkspacePermissionManager(authorized=False)
        security = PathSecurity(
            PathSecurityConfig(allowed_roots=(tmp_path,)), permissions=permissions
        )

        with pytest.raises(PathNotAllowedError):
            security.resolve(
                str(tmp_path / "a.txt"), operation=WorkspaceOperation.WRITE
            )

        assert len(permissions.calls) == 1
