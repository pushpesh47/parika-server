"""
PARIKA Filesystem Module - Manifest

Defines the static ModuleManifest describing the Filesystem Module.
"""

from __future__ import annotations

from parika.core.module_manager.manifest import ModuleManifest
from parika.core.module_manager.module import Module
from parika.core.module_manager.state import ModuleState

from .driver import FilesystemModuleDriver

FILESYSTEM_MODULE_ID = "filesystem"
FILESYSTEM_MODULE_VERSION = "1.0.0"


def create_filesystem_module_manifest() -> ModuleManifest:
    """
    Build the immutable ModuleManifest for the Filesystem Module.
    """

    return ModuleManifest(
        id=FILESYSTEM_MODULE_ID,
        name="Filesystem",
        version=FILESYSTEM_MODULE_VERSION,
        description=(
            "Provides local filesystem access (read, write, list, "
            "search, copy, move, delete, mkdir, exists, info, walk, "
            "permissions, watch) confined to a configured allowlist "
            "of root directories."
        ),
        author="PARIKA",
        license="MIT",
        tags=("filesystem", "system"),
        required_permissions=("filesystem.access",),
        driver=(
            "parika.modules.filesystem.driver.FilesystemModuleDriver"
        ),
    )


def create_filesystem_module(driver: FilesystemModuleDriver) -> Module:
    """
    Build the immutable Module descriptor for the Filesystem Module.

    Args:
        driver:
            Constructed FilesystemModuleDriver instance for this
            module.

    Returns:
        A Module ready to be registered with ModuleManager.
    """

    return Module(
        id=FILESYSTEM_MODULE_ID,
        manifest=create_filesystem_module_manifest(),
        driver=driver,
        state=ModuleState.INACTIVE,
    )
