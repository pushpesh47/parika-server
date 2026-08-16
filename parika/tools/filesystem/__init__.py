"""
PARIKA Filesystem Tool package.

Implements the `filesystem.read`, `filesystem.write`,
`filesystem.list`, `filesystem.search`, `filesystem.copy`,
`filesystem.move`, `filesystem.delete`, `filesystem.mkdir`,
`filesystem.exists`, `filesystem.info`, `filesystem.walk`,
`filesystem.permissions`, and `filesystem.watch` Capabilities -
local, standard-library-only filesystem access confined to a
configured allowlist of root directories.

Public exports provide everything needed to register these Tools with
ToolManager, either directly or through the Filesystem Module.
"""

from __future__ import annotations

from .config import FilesystemToolConfig, load_filesystem_config
from .driver import FilesystemToolDriver
from .exceptions import (
    FilesystemAlreadyExistsError,
    FilesystemOperationNotPermittedError,
    FilesystemPathNotFoundError,
    FilesystemToolError,
    InvalidFilesystemArgumentError,
    PathNotAllowedError,
)
from .manifest import (
    FILESYSTEM_OPERATIONS,
    FILESYSTEM_TOOL_VERSION,
    FilesystemOperation,
    FilesystemOperationSpec,
    create_filesystem_tool,
)
from .security import PathSecurity, PathSecurityConfig

__all__ = [
    "FILESYSTEM_OPERATIONS",
    "FILESYSTEM_TOOL_VERSION",
    "FilesystemAlreadyExistsError",
    "FilesystemOperation",
    "FilesystemOperationNotPermittedError",
    "FilesystemOperationSpec",
    "FilesystemPathNotFoundError",
    "FilesystemToolConfig",
    "FilesystemToolDriver",
    "FilesystemToolError",
    "InvalidFilesystemArgumentError",
    "PathNotAllowedError",
    "PathSecurity",
    "PathSecurityConfig",
    "create_filesystem_tool",
    "load_filesystem_config",
]
