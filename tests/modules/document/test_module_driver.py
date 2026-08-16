"""
Unit tests for DocumentModuleDriver, mirroring
`tests/modules/vision/test_vision_module_driver.py`'s own wiring shape.
"""

from __future__ import annotations

import pytest

from parika.core.brain.brain import Brain
from parika.core.capability_executor.capability_executor import CapabilityExecutor
from parika.core.capability_registry.capability_category import CapabilityCategory
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.capability_resolver.capability_resolver import CapabilityResolver
from parika.core.planner.planner import Planner
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.task_manager.task_manager import TaskManager
from parika.core.tool_manager.tool_manager import ToolManager
from parika.modules.document.module_driver import (
    MODULE_HEALTH_COMPONENT_ID,
    PROVIDER_ANALYZE_CONTENT_CAPABILITY_ID,
    _ANALYSIS_SPECS,
    _DETERMINISTIC_SPECS,
    _EXTRACTION_SPECS,
    _READING_SPECS,
    DocumentModuleDriver,
)

_ALL_TOOL_CAPABILITY_IDS = (
    [f"document.{spec.name}" for spec in _READING_SPECS]
    + [f"document.extract_{spec.facet}" for spec in _EXTRACTION_SPECS]
    + [f"document.{spec.name}" for spec in _ANALYSIS_SPECS]
    + [f"document.{spec.name}" for spec in _DETERMINISTIC_SPECS]
)
_ALL_TOOL_IDS = [f"tool.{capability_id.replace('.', '_')}" for capability_id in _ALL_TOOL_CAPABILITY_IDS]


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


def test_start_registers_every_capability_and_tool(wiring, logger) -> None:
    capability_registry, tool_manager, brain = wiring

    driver = DocumentModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
    )
    driver.start()

    for capability_id, tool_id in zip(_ALL_TOOL_CAPABILITY_IDS, _ALL_TOOL_IDS):
        assert capability_registry.contains(capability_id)
        assert tool_manager.contains(tool_id)

    assert capability_registry.contains(PROVIDER_ANALYZE_CONTENT_CAPABILITY_ID)

    driver.stop()

    for capability_id, tool_id in zip(_ALL_TOOL_CAPABILITY_IDS, _ALL_TOOL_IDS):
        assert not capability_registry.contains(capability_id)
        assert not tool_manager.contains(tool_id)

    assert not capability_registry.contains(PROVIDER_ANALYZE_CONTENT_CAPABILITY_ID)


def test_tool_capabilities_are_tool_category(wiring, logger) -> None:
    capability_registry, tool_manager, brain = wiring

    driver = DocumentModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
    )
    driver.start()

    for capability_id in _ALL_TOOL_CAPABILITY_IDS:
        definition = capability_registry.get(capability_id)
        assert definition.category is CapabilityCategory.TOOL
        assert "tool_affordance" in definition.metadata

    provider_definition = capability_registry.get(PROVIDER_ANALYZE_CONTENT_CAPABILITY_ID)
    assert provider_definition.category is CapabilityCategory.LLM

    driver.stop()


def test_provider_capability_is_never_discoverable_as_tool_category(wiring, logger) -> None:
    capability_registry, tool_manager, brain = wiring

    driver = DocumentModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
    )
    driver.start()

    discoverable_ids = {
        definition.id
        for definition in capability_registry.find(
            category=CapabilityCategory.TOOL, enabled=True
        )
    }

    for capability_id in _ALL_TOOL_CAPABILITY_IDS:
        assert capability_id in discoverable_ids

    assert PROVIDER_ANALYZE_CONTENT_CAPABILITY_ID not in discoverable_ids

    driver.stop()


def test_disabled_by_configuration_registers_nothing(logger, event_bus) -> None:
    from parika.core.configuration.configuration import Configuration

    capability_registry = CapabilityRegistry(event_bus, logger)
    capability_resolver = CapabilityResolver(
        capability_registry=capability_registry, logger=logger
    )
    policy_engine = PolicyEngine(event_bus=event_bus, logger=logger)
    provider_manager = ProviderManager(event_bus=event_bus, logger=logger)
    tool_manager = ToolManager(event_bus, logger)
    resource_manager = ResourceManager(configuration=Configuration(), logger=logger)
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

    configuration = Configuration()
    configuration._config = {"document": {"enabled": False}}  # noqa: SLF001

    driver = DocumentModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
        configuration=configuration,
    )
    driver.start()

    for capability_id in _ALL_TOOL_CAPABILITY_IDS:
        assert not capability_registry.contains(capability_id)

    assert not capability_registry.contains(PROVIDER_ANALYZE_CONTENT_CAPABILITY_ID)


def test_health_check_reports_healthy(wiring, logger, event_bus) -> None:
    from parika.core.health_manager.health_manager import HealthManager
    from parika.core.health_manager.health_status import HealthStatus

    capability_registry, tool_manager, brain = wiring
    health_manager = HealthManager(event_bus=event_bus, logger=logger)

    driver = DocumentModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
        health_manager=health_manager,
    )
    driver.start()

    result = health_manager.run_check(MODULE_HEALTH_COMPONENT_ID)
    assert result.status is HealthStatus.HEALTHY

    driver.stop()
