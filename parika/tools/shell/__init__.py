"""
PARIKA Shell Tool package.

Implements the `shell.execute`, `shell.background`, `shell.processes`,
and `shell.kill` Capabilities - local, `subprocess`-based command
execution, gated entirely through the shared
`WorkspacePermissionManager` (see
`parika.core.permission_manager.workspace_permission_manager`). The
Shell Tool never implements its own permission logic.

Public exports provide everything needed to register these Tools with
ToolManager, either directly or through the Shell Module.
"""

from __future__ import annotations

from .config import ShellToolConfig, load_shell_config
from .driver import ShellToolDriver
from .exceptions import (
    InvalidShellArgumentError,
    ShellBackgroundLimitExceededError,
    ShellPermissionDeniedError,
    ShellToolError,
    UnknownProcessError,
)
from .manifest import (
    SHELL_OPERATIONS,
    SHELL_TOOL_VERSION,
    ShellOperation,
    ShellOperationSpec,
    create_shell_tool,
)
from .process_record import ShellProcessRecord, ShellProcessStatus
from .process_registry import ShellProcessRegistry

__all__ = [
    "SHELL_OPERATIONS",
    "SHELL_TOOL_VERSION",
    "InvalidShellArgumentError",
    "ShellBackgroundLimitExceededError",
    "ShellOperation",
    "ShellOperationSpec",
    "ShellPermissionDeniedError",
    "ShellProcessRecord",
    "ShellProcessRegistry",
    "ShellProcessStatus",
    "ShellToolConfig",
    "ShellToolDriver",
    "ShellToolError",
    "UnknownProcessError",
    "create_shell_tool",
    "load_shell_config",
]
