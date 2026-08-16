"""
PARIKA Coding Agent Module - Manifest
"""

from __future__ import annotations

from parika.core.module_manager.manifest import ModuleManifest
from parika.core.module_manager.module import Module
from parika.core.module_manager.state import ModuleState

from .module_driver import CodingAgentModuleDriver

CODING_AGENT_MODULE_ID = "coding_agent"
CODING_AGENT_MODULE_VERSION = "1.0.0"


def create_coding_agent_module_manifest() -> ModuleManifest:
    return ModuleManifest(
        id=CODING_AGENT_MODULE_ID,
        name="Coding Agent",
        version=CODING_AGENT_MODULE_VERSION,
        description=(
            "Registers `coding.execute_task` (a pure orchestrator over "
            "Planner/Brain/the Coding Tool/the Filesystem Tool/the "
            "Shell Tool) and `coding.plan_change` (its LLM-category "
            "decomposition capability). Internally pluggable: multiple "
            "CodingAgent implementations may be registered without "
            "changing this Capability's public shape."
        ),
        author="PARIKA",
        license="MIT",
        tags=("coding", "agent", "automation"),
        driver="parika.modules.coding_agent.module_driver.CodingAgentModuleDriver",
    )


def create_coding_agent_module(driver: CodingAgentModuleDriver) -> Module:
    return Module(
        id=CODING_AGENT_MODULE_ID,
        manifest=create_coding_agent_module_manifest(),
        driver=driver,
        state=ModuleState.INACTIVE,
    )
