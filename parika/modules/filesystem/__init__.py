"""
PARIKA Filesystem Module package.

Integrates the Filesystem Tool into PARIKA through ModuleManager,
CapabilityRegistry, and ToolManager.
"""

from __future__ import annotations

from .driver import MODULE_HEALTH_COMPONENT_ID, FilesystemModuleDriver
from .manifest import (
    FILESYSTEM_MODULE_ID,
    FILESYSTEM_MODULE_VERSION,
    create_filesystem_module,
    create_filesystem_module_manifest,
)

__all__ = [
    "FILESYSTEM_MODULE_ID",
    "FILESYSTEM_MODULE_VERSION",
    "MODULE_HEALTH_COMPONENT_ID",
    "FilesystemModuleDriver",
    "create_filesystem_module",
    "create_filesystem_module_manifest",
]
