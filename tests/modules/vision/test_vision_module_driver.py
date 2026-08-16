"""
Unit tests for VisionModuleDriver, mirroring
`tests/modules/coding_agent/test_coding_agent_module_driver.py`'s own
wiring shape.
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
from parika.modules.vision.module_driver import (
    MODULE_HEALTH_COMPONENT_ID,
    VisionModuleDriver,
    _VISION_EXTENDED_TOOL_SPECS,
    _VISION_TOOL_SPECS,
)


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

    driver = VisionModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
    )
    driver.start()

    for spec in _VISION_TOOL_SPECS:
        assert capability_registry.contains(spec.tool_capability_id)
        assert capability_registry.contains(spec.provider_capability_id)
        assert tool_manager.contains(spec.tool_id)

    driver.stop()

    for spec in _VISION_TOOL_SPECS:
        assert not capability_registry.contains(spec.tool_capability_id)
        assert not capability_registry.contains(spec.provider_capability_id)
        assert not tool_manager.contains(spec.tool_id)


def test_start_registers_every_extended_capability_and_tool(wiring, logger) -> None:
    """
    Mirrors `test_start_registers_every_capability_and_tool` for the
    22 deterministic-first Phase 1-5 Capabilities
    (`_VISION_EXTENDED_TOOL_SPECS`), each of which optionally also
    registers its own distinct `vision.provider_*` Capability.
    """

    capability_registry, tool_manager, brain = wiring

    driver = VisionModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
    )
    driver.start()

    for spec in _VISION_EXTENDED_TOOL_SPECS:
        assert capability_registry.contains(spec.tool_capability_id)
        assert tool_manager.contains(spec.tool_id)

        if spec.provider_capability_id is not None:
            assert capability_registry.contains(spec.provider_capability_id)

    driver.stop()

    for spec in _VISION_EXTENDED_TOOL_SPECS:
        assert not capability_registry.contains(spec.tool_capability_id)
        assert not tool_manager.contains(spec.tool_id)

        if spec.provider_capability_id is not None:
            assert not capability_registry.contains(spec.provider_capability_id)


def test_extended_capabilities_are_tool_category_and_provider_are_vision_category(
    wiring, logger
) -> None:
    capability_registry, tool_manager, brain = wiring

    driver = VisionModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
    )
    driver.start()

    for spec in _VISION_EXTENDED_TOOL_SPECS:
        tool_capability = capability_registry.get(spec.tool_capability_id)
        assert tool_capability.category is CapabilityCategory.TOOL
        assert "tool_affordance" in tool_capability.metadata

        if spec.provider_capability_id is not None:
            provider_capability = capability_registry.get(spec.provider_capability_id)
            assert provider_capability.category is CapabilityCategory.VISION

    driver.stop()


def test_extended_provider_capabilities_are_never_discoverable_as_tool_category(
    wiring, logger
) -> None:
    capability_registry, tool_manager, brain = wiring

    driver = VisionModuleDriver(
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

    for spec in _VISION_EXTENDED_TOOL_SPECS:
        assert spec.tool_capability_id in discoverable_ids

        if spec.provider_capability_id is not None:
            assert spec.provider_capability_id not in discoverable_ids

    driver.stop()


def test_no_capability_or_tool_id_collides_across_original_and_extended_specs() -> None:
    """
    Guards against ever accidentally duplicating a Capability/Tool id
    between the original seven Provider-backed specs and the 22
    deterministic-first extended specs -- a direct check of the
    "DO NOT duplicate existing capabilities or tools" requirement.
    """

    all_tool_capability_ids = [spec.tool_capability_id for spec in _VISION_TOOL_SPECS] + [
        spec.tool_capability_id for spec in _VISION_EXTENDED_TOOL_SPECS
    ]
    all_tool_ids = [spec.tool_id for spec in _VISION_TOOL_SPECS] + [
        spec.tool_id for spec in _VISION_EXTENDED_TOOL_SPECS
    ]

    assert len(all_tool_capability_ids) == len(set(all_tool_capability_ids))
    assert len(all_tool_ids) == len(set(all_tool_ids))


def test_tool_capabilities_are_tool_category_and_provider_are_vision_category(
    wiring, logger
) -> None:
    capability_registry, tool_manager, brain = wiring

    driver = VisionModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
    )
    driver.start()

    for spec in _VISION_TOOL_SPECS:
        tool_capability = capability_registry.get(spec.tool_capability_id)
        provider_capability = capability_registry.get(spec.provider_capability_id)

        assert tool_capability.category is CapabilityCategory.TOOL
        assert provider_capability.category is CapabilityCategory.VISION
        assert "tool_affordance" in tool_capability.metadata

    driver.stop()


def test_provider_capabilities_are_never_discoverable_as_tool_category(
    wiring, logger
) -> None:
    """
    Mirrors the OCR Module's own guarantee: only TOOL-category
    Capabilities are ever advertised to the model (Automatic
    Capability Discovery, `capability_context.discover_capabilities()`).
    """

    capability_registry, tool_manager, brain = wiring

    driver = VisionModuleDriver(
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

    for spec in _VISION_TOOL_SPECS:
        assert spec.tool_capability_id in discoverable_ids
        assert spec.provider_capability_id not in discoverable_ids

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
    resource_manager = ResourceManager(
        configuration=Configuration(), logger=logger
    )
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
    configuration._config = {"vision": {"enabled": False}}  # noqa: SLF001

    driver = VisionModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
        configuration=configuration,
    )
    driver.start()

    for spec in _VISION_TOOL_SPECS:
        assert not capability_registry.contains(spec.tool_capability_id)
        assert not capability_registry.contains(spec.provider_capability_id)
        assert not tool_manager.contains(spec.tool_id)


def test_health_check_reports_healthy(wiring, logger, event_bus) -> None:
    from parika.core.health_manager.health_manager import HealthManager
    from parika.core.health_manager.health_status import HealthStatus

    capability_registry, tool_manager, brain = wiring
    health_manager = HealthManager(event_bus=event_bus, logger=logger)

    driver = VisionModuleDriver(
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
