"""
PARIKA Shell Module - Manifest

Defines the static ModuleManifest describing the Shell Module.
"""

from __future__ import annotations

from parika.core.module_manager.manifest import ModuleManifest
from parika.core.module_manager.module import Module
from parika.core.module_manager.state import ModuleState

from .driver import ShellModuleDriver

SHELL_MODULE_ID = "shell"
SHELL_MODULE_VERSION = "1.0.0"


def create_shell_module_manifest() -> ModuleManifest:
    """
    Build the immutable ModuleManifest for the Shell Module.
    """

    return ModuleManifest(
        id=SHELL_MODULE_ID,
        name="Shell",
        version=SHELL_MODULE_VERSION,
        description=(
            "Provides local shell command execution (execute, "
            "background, processes, kill), gated entirely through the "
            "shared Workspace Permission Manager."
        ),
        author="PARIKA",
        license="MIT",
        tags=("shell", "system"),
        required_permissions=("shell.execute",),
        driver=("parika.modules.shell.driver.ShellModuleDriver"),
    )


def create_shell_module(driver: ShellModuleDriver) -> Module:
    """
    Build the immutable Module descriptor for the Shell Module.

    Args:
        driver:
            Constructed ShellModuleDriver instance for this module.

    Returns:
        A Module ready to be registered with ModuleManager.
    """

    return Module(
        id=SHELL_MODULE_ID,
        manifest=create_shell_module_manifest(),
        driver=driver,
        state=ModuleState.INACTIVE,
    )
