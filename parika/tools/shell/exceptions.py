"""
PARIKA Shell Tool exceptions.

Defines the exception hierarchy used by the Shell Tool. Every
exception here is uniformly wrapped into `ToolExecutionError` by
`ToolManager.execute()`, exactly like every existing Tool's own
exception hierarchy.
"""

from __future__ import annotations


class ShellToolError(Exception):
    """
    Base exception for all Shell Tool errors.
    """


class InvalidShellArgumentError(ShellToolError):
    """
    Raised when a required argument is missing or invalid.
    """


class ShellPermissionDeniedError(ShellToolError):
    """
    Raised when `WorkspacePermissionManager` denies `Execute`
    permission for a command's working directory.

    The Shell Tool never maintains its own permission cache or
    allow/deny logic; this exception is raised only after
    `WorkspacePermissionManager.check()` returns an unauthorized
    decision (see `driver.py`).
    """


class UnknownProcessError(ShellToolError):
    """
    Raised when `shell.processes`/`shell.kill` is given a `process_id`
    this Shell Tool's own `ShellProcessRegistry` never spawned.
    """


class ShellBackgroundLimitExceededError(ShellToolError):
    """
    Raised when `shell.background` would exceed
    `[shell].max_background_processes`.
    """
