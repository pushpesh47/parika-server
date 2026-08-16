"""
PARIKA Filesystem Tool Exceptions

Defines the exception hierarchy used by the Filesystem Tool.

All Filesystem Tool exceptions derive from `FilesystemToolError` so
that `ToolManager` can uniformly wrap them as `ToolExecutionError`,
exactly like every other Tool in PARIKA (see `runtime_info` and
`web_search`).
"""

from __future__ import annotations


class FilesystemToolError(Exception):
    """
    Base exception for all Filesystem Tool errors.
    """


class InvalidFilesystemArgumentError(FilesystemToolError):
    """
    Raised when a request supplies a missing, empty, or otherwise
    invalid argument (e.g. a non-string `path`).
    """


class PathNotAllowedError(FilesystemToolError):
    """
    Raised when a requested path resolves outside every configured
    `allowed_roots` entry, or when no root is configured at all.

    This is a security boundary, not a convenience check: it is
    enforced after resolving symlinks and `..` segments, so it cannot
    be bypassed by a symlink that appears inside an allowed root but
    points outside of it.
    """


class FilesystemPathNotFoundError(FilesystemToolError):
    """
    Raised when an operation requires a path that does not exist.
    """


class FilesystemAlreadyExistsError(FilesystemToolError):
    """
    Raised when an operation would silently overwrite an existing
    path and the caller did not explicitly permit that.
    """


class FilesystemOperationNotPermittedError(FilesystemToolError):
    """
    Raised when a destructive or mutating operation (`write`,
    `delete`, `mkdir`, `copy`, `move`) is attempted while disabled by
    configuration (`[filesystem].allow_write` / `allow_delete`).
    """
