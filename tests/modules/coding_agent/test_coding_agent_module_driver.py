"""
Unit tests for CodingAgentModuleDriver.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parika.core.brain.brain import Brain
from parika.core.capability_executor.capability_executor import CapabilityExecutor
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.capability_resolver.capability_resolver import CapabilityResolver
from parika.core.planner.planner import Planner
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.task_manager.task_manager import TaskManager
from parika.core.tool_manager.tool_manager import ToolManager
from parika.modules.coding_agent.module_driver import (
    EXECUTE_TASK_CAPABILITY_ID,
    EXECUTE_TASK_TOOL_ID,
    CodingAgentModuleDriver,
)
from parika.modules.coding_agent.standard_agent import PLAN_CHANGE_CAPABILITY_ID


@pytest.fixture()
def wiring(logger, event_bus, configuration):
    capability_registry = CapabilityRegistry(event_bus, logger)
    capability_resolver = CapabilityResolver(
        capability_registry=capability_registry, logger=logger
    )
    policy_engine = PolicyEngine(event_bus=event_bus, logger=logger)
    provider_manager = ProviderManager(event_bus=event_bus, logger=logger)
    tool_manager = ToolManager(event_bus, logger)
    resource_manager = ResourceManager(configuration=configuration, logger=logger)

    capability_executor = CapabilityExecutor(
        event_bus=event_bus,
        logger=logger,
        tool_manager=tool_manager,
        provider_manager=provider_manager,
    )
    task_manager = TaskManager(
        event_bus=event_bus, logger=logger, capability_executor=capability_executor
    )
    planner = Planner(
        capability_resolver=capability_resolver,
        resource_manager=resource_manager,
        policy_engine=policy_engine,
        provider_manager=provider_manager,
        tool_manager=tool_manager,
        logger=logger,
    )
    brain = Brain(planner=planner, task_manager=task_manager, logger=logger)

    return capability_registry, tool_manager, brain


def test_start_registers_capabilities_and_tool(
    wiring, logger, tmp_path: Path
) -> None:
    capability_registry, tool_manager, brain = wiring

    driver = CodingAgentModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
        default_workspace=tmp_path,
    )
    driver.start()

    assert capability_registry.contains(EXECUTE_TASK_CAPABILITY_ID)
    assert capability_registry.contains(PLAN_CHANGE_CAPABILITY_ID)
    assert tool_manager.contains(EXECUTE_TASK_TOOL_ID)

    driver.stop()

    assert not capability_registry.contains(EXECUTE_TASK_CAPABILITY_ID)
    assert not capability_registry.contains(PLAN_CHANGE_CAPABILITY_ID)
    assert not tool_manager.contains(EXECUTE_TASK_TOOL_ID)


def test_execute_task_capability_is_registered_as_tool_backed(
    wiring, logger, tmp_path: Path
) -> None:
    capability_registry, _, brain = wiring[0], wiring[1], wiring[2]

    driver = CodingAgentModuleDriver(
        capability_registry=wiring[0],
        tool_manager=wiring[1],
        brain=wiring[2],
        logger=logger,
        default_workspace=tmp_path,
    )
    driver.start()

    from parika.core.capability_registry.capability_category import CapabilityCategory

    execute_task = capability_registry.get(EXECUTE_TASK_CAPABILITY_ID)
    plan_change = capability_registry.get(PLAN_CHANGE_CAPABILITY_ID)

    assert execute_task.category is CapabilityCategory.TOOL
    assert plan_change.category is CapabilityCategory.LLM

    driver.stop()
