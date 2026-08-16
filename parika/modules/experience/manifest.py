"""
PARIKA Experience Module - Manifest

Defines the static ModuleManifest describing the Experience Module.
"""

from __future__ import annotations

from parika.core.module_manager.manifest import ModuleManifest
from parika.core.module_manager.module import Module
from parika.core.module_manager.state import ModuleState

from .driver import ExperienceModuleDriver

EXPERIENCE_MODULE_ID = "experience"
EXPERIENCE_MODULE_VERSION = "1.0.0"


def create_experience_module_manifest() -> ModuleManifest:
    """Build the immutable ModuleManifest for the Experience Module."""

    return ModuleManifest(
        id=EXPERIENCE_MODULE_ID,
        name="Experience",
        version=EXPERIENCE_MODULE_VERSION,
        description=(
            "Records Task execution outcomes as Experience data and "
            "exposes an aggregated historical-success-rate signal that "
            "Planner's optional ExperienceRule may consult."
        ),
        author="PARIKA",
        license="MIT",
        tags=("experience", "learning", "telemetry"),
        driver="parika.modules.experience.driver.ExperienceModuleDriver",
    )


def create_experience_module(driver: ExperienceModuleDriver) -> Module:
    """Build the immutable Module descriptor for the Experience Module."""

    return Module(
        id=EXPERIENCE_MODULE_ID,
        manifest=create_experience_module_manifest(),
        driver=driver,
        state=ModuleState.INACTIVE,
    )
