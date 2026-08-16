"""
PARIKA Runtime Info Module - Manifest

Defines the static ModuleManifest describing the Runtime Info Module.
"""

from __future__ import annotations

from parika.core.module_manager.manifest import ModuleManifest
from parika.core.module_manager.module import Module
from parika.core.module_manager.state import ModuleState

from .driver import RuntimeInfoModuleDriver

RUNTIME_INFO_MODULE_ID = "runtime_info"
RUNTIME_INFO_MODULE_VERSION = "1.0.0"


def create_runtime_info_module_manifest() -> ModuleManifest:
    """
    Build the immutable ModuleManifest for the Runtime Info Module.
    """

    return ModuleManifest(
        id=RUNTIME_INFO_MODULE_ID,
        name="Runtime Info",
        version=RUNTIME_INFO_MODULE_VERSION,
        description=(
            "Provides the runtime.current_datetime Capability: the "
            "current date and time, read from the system clock."
        ),
        author="PARIKA",
        license="MIT",
        tags=("runtime", "system", "datetime"),
        driver=(
            "parika.modules.runtime_info.driver.RuntimeInfoModuleDriver"
        ),
    )


def create_runtime_info_module(driver: RuntimeInfoModuleDriver) -> Module:
    """
    Build the immutable Module descriptor for the Runtime Info Module.

    Args:
        driver:
            Constructed RuntimeInfoModuleDriver instance for this
            module.

    Returns:
        A Module ready to be registered with ModuleManager.
    """

    return Module(
        id=RUNTIME_INFO_MODULE_ID,
        manifest=create_runtime_info_module_manifest(),
        driver=driver,
        state=ModuleState.INACTIVE,
    )
