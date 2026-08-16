"""
PARIKA Test Slow Tool - Manifest

Defines the static ModuleManifest describing the Test Slow Module.
"""

from __future__ import annotations

from parika.core.module_manager.manifest import ModuleManifest
from parika.core.module_manager.module import Module
from parika.core.module_manager.state import ModuleState

from .driver import TestSlowModuleDriver, create_test_slow_tool

TEST_SLOW_MODULE_ID = "test_slow"
TEST_SLOW_MODULE_VERSION = "1.0.0"
TEST_SLOW_OPERATION_CAPABILITY_ID = "test.slow_operation"
TEST_SLOW_OPERATION_NAME = "Test Slow Operation"
TEST_SLOW_OPERATION_DESCRIPTION = (
    "A test capability that sleeps for a configurable duration "
    "to simulate a long-running operation."
)


def create_test_slow_module_manifest() -> ModuleManifest:
    """
    Build the immutable ModuleManifest for the Test Slow Module.
    """

    return ModuleManifest(
        id=TEST_SLOW_MODULE_ID,
        name="Test Slow",
        version=TEST_SLOW_MODULE_VERSION,
        description=TEST_SLOW_OPERATION_DESCRIPTION,
        author="PARIKA",
        license="MIT",
        tags=("test", "concurrency"),
        required_permissions=(),
        driver="parika.tools.test_slow.driver.TestSlowModuleDriver",
    )


def create_test_slow_module(
    *,
    capability_registry: CapabilityRegistry,
    tool_manager: ToolManager,
    logger: Logger,
    default_delay: float = 0.0,
) -> Module:
    """
    Build the immutable Module descriptor for the Test Slow Module.

    Args:
        capability_registry:
            Registry used to register/unregister the capability.
        tool_manager:
            Manager used to register/unregister the tool.
        logger:
            PARIKA Logger component.
        default_delay:
            Default delay in seconds for the slow operation.

    Returns:
        A Module ready to be registered with ModuleManager.
    """

    driver = TestSlowModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        logger=logger,
        default_delay=default_delay,
    )
    
    return Module(
        id=TEST_SLOW_MODULE_ID,
        manifest=create_test_slow_module_manifest(),
        driver=driver,
        state=ModuleState.INACTIVE,
    )