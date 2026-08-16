"""
PARIKA Memory Module - Manifest

Defines the static ModuleManifest describing the Memory Module.
"""

from __future__ import annotations

from parika.core.module_manager.manifest import ModuleManifest
from parika.core.module_manager.module import Module
from parika.core.module_manager.state import ModuleState

from .driver import MemoryModuleDriver

MEMORY_MODULE_ID = "memory"
MEMORY_MODULE_VERSION = "1.0.0"


def create_memory_module_manifest() -> ModuleManifest:
    """Build the immutable ModuleManifest for the Memory Module."""

    return ModuleManifest(
        id=MEMORY_MODULE_ID,
        name="Memory",
        version=MEMORY_MODULE_VERSION,
        description=(
            "Advertises memory.remember/search/forget as native, "
            "model-callable tools backed by MemoryManager, so PARIKA "
            "never falsely claims to remember something it did not "
            "actually persist."
        ),
        author="PARIKA",
        license="MIT",
        tags=("memory",),
        driver="parika.modules.memory.driver.MemoryModuleDriver",
    )


def create_memory_module(driver: MemoryModuleDriver) -> Module:
    """Build the immutable Module descriptor for the Memory Module."""

    return Module(
        id=MEMORY_MODULE_ID,
        manifest=create_memory_module_manifest(),
        driver=driver,
        state=ModuleState.INACTIVE,
    )
