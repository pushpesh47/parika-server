"""
PARIKA Autonomous Module Manifest

Defines the module identity and creation function for the Autonomous module.
"""
from __future__ import annotations

from parika.core.module_manager.manifest import ModuleManifest
from parika.core.module_manager.module import Module
from parika.core.module_manager.state import ModuleState

from .driver import AutonomousModuleDriver

AUTONOMOUS_MODULE_ID = "autonomous"
AUTONOMOUS_MODULE_VERSION = "1.0.0"


def create_autonomous_module_manifest() -> ModuleManifest:
    """
    Build the immutable ModuleManifest for the Autonomous Module.
    """

    return ModuleManifest(
        id=AUTONOMOUS_MODULE_ID,
        name="Autonomous Mission Operations",
        version=AUTONOMOUS_MODULE_VERSION,
        description="Provides mission.get_result and mission.list_tasks capabilities for autonomous execution.",
        author="PARIKA",
        license="MIT",
        tags=("autonomous", "mission", "task"),
        driver=(
            "parika.modules.autonomous.driver.AutonomousModuleDriver"
        ),
    )


def create_autonomous_module(driver: AutonomousModuleDriver) -> Module:
    """Create the Autonomous module."""
    return Module(
        id=AUTONOMOUS_MODULE_ID,
        manifest=create_autonomous_module_manifest(),
        driver=driver,
        state=ModuleState.INACTIVE,
    )