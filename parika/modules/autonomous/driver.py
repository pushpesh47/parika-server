"""
PARIKA Autonomous Module Driver

Registers the autonomous mission tools with the ToolManager.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from parika.tools.autonomous.driver import create_autonomous_tool_driver
from parika.tools.autonomous.manifest import AUTONOMOUS_OPERATIONS, create_autonomous_tool

if TYPE_CHECKING:
    from parika.core.capability_registry.capability_registry import CapabilityRegistry
    from parika.core.tool_manager.tool_manager import ToolManager
    from parika.core.health_manager.health_manager import HealthManager
    from parika.core.logger.logger import Logger
    from parika.core.database.pool import PoolManager
    from parika.core.event_bus.event_bus import EventBus


class AutonomousModuleDriver:
    """Autonomous module driver - registers autonomous mission tools."""
    pass


def load_autonomous_module(
    *,
    capability_registry: "CapabilityRegistry",
    tool_manager: "ToolManager",
    logger: "Logger",
    health_manager: "HealthManager",
    pool_manager: "PoolManager",
    event_bus: "EventBus",
) -> AutonomousModuleDriver:
    """
    Load and register the autonomous mission tools.
    
    This registers the autonomous tool operations (mission.get_result, mission.list_tasks)
    with the ToolManager so they can be discovered and executed.
    """
    driver = AutonomousModuleDriver()
    
    # Create the autonomous tool driver
    autonomous_tool_driver = create_autonomous_tool_driver(
        pool_manager=pool_manager,
        logger=logger,
        event_bus=event_bus,
    )
    
    # Register each autonomous tool operation
    for spec in AUTONOMOUS_OPERATIONS:
        tool = create_autonomous_tool(spec)
        tool_manager.register(tool, autonomous_tool_driver)
    
    return driver