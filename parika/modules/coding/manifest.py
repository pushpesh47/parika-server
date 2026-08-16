"""
PARIKA Coding Module - Manifest

Defines the static ModuleManifest describing the Coding Module -- the
registration Module for the Coding Tool (see
docs/development/Module_Guide.md section
4.1: the Coding Tool itself lives in `parika/tools/coding/`; this
Module is its `parika/modules/filesystem/`-shaped registration
counterpart).
"""

from __future__ import annotations

from parika.core.module_manager.manifest import ModuleManifest
from parika.core.module_manager.module import Module
from parika.core.module_manager.state import ModuleState

from .driver import CodingModuleDriver

CODING_MODULE_ID = "coding"
CODING_MODULE_VERSION = "1.0.0"


def create_coding_module_manifest() -> ModuleManifest:
    """
    Build the immutable ModuleManifest for the Coding Module.
    """

    return ModuleManifest(
        id=CODING_MODULE_ID,
        name="Coding",
        version=CODING_MODULE_VERSION,
        description=(
            "Registers every `coding.*` Capability and its Coding "
            "Tool: semantic source-code parsing, symbol indexing, "
            "search, cross-reference/call-hierarchy analysis, rename/"
            "refactor planning, patch generation, documentation "
            "drafting, formatting/linting (via the Shell Tool), "
            "complexity, duplicate, and dead-code detection."
        ),
        author="PARIKA",
        license="MIT",
        tags=("coding", "development", "indexing"),
        driver="parika.modules.coding.driver.CodingModuleDriver",
    )


def create_coding_module(driver: CodingModuleDriver) -> Module:
    """
    Build the immutable Module descriptor for the Coding Module.
    """

    return Module(
        id=CODING_MODULE_ID,
        manifest=create_coding_module_manifest(),
        driver=driver,
        state=ModuleState.INACTIVE,
    )
