"""
Unit tests for `GenerationModuleDriver`, mirroring
`tests/modules/vision/test_vision_module_driver.py`'s own wiring
shape.
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
from parika.modules.generation.module_driver import (
    MODULE_HEALTH_COMPONENT_ID,
    GenerationModuleDriver,
    _GENERATION_TOOL_SPECS,
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

    driver = GenerationModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
    )
    driver.start()

    for spec in _GENERATION_TOOL_SPECS:
        assert capability_registry.contains(spec.tool_capability_id)
        assert capability_registry.contains(spec.provider_capability_id)
        assert tool_manager.contains(spec.tool_id)

        tool_definition = capability_registry.get(spec.tool_capability_id)
        assert tool_definition.category is CapabilityCategory.TOOL
        assert "tool_affordance" in tool_definition.metadata

        provider_definition = capability_registry.get(spec.provider_capability_id)
        assert provider_definition.category is spec.provider_category

    driver.stop()

    for spec in _GENERATION_TOOL_SPECS:
        assert not capability_registry.contains(spec.tool_capability_id)
        assert not capability_registry.contains(spec.provider_capability_id)
        assert not tool_manager.contains(spec.tool_id)


def test_exact_five_capabilities_registered(wiring, logger) -> None:
    assert len(_GENERATION_TOOL_SPECS) == 5

    expected_ids = {
        "image.generate",
        "image.edit",
        "video.generate",
        "video.generate_from_image",
        "video.edit",
    }
    assert {spec.tool_capability_id for spec in _GENERATION_TOOL_SPECS} == expected_ids


def test_provider_capabilities_use_generation_categories(logger) -> None:
    for spec in _GENERATION_TOOL_SPECS:
        assert spec.provider_category in (
            CapabilityCategory.IMAGE_GENERATION,
            CapabilityCategory.VIDEO_GENERATION,
        )


def test_disabled_module_registers_nothing(wiring, logger, configuration) -> None:
    capability_registry, tool_manager, brain = wiring
    configuration_dict = {"generation": {"enabled": False}}

    class _DisabledConfiguration:
        def get(self, key, default=None):
            if key == "generation.enabled":
                return False
            return default

    driver = GenerationModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
        configuration=_DisabledConfiguration(),
    )
    driver.start()

    for spec in _GENERATION_TOOL_SPECS:
        assert not capability_registry.contains(spec.tool_capability_id)

    driver.stop()


def test_health_check_registered(wiring, logger, event_bus) -> None:
    from parika.core.health_manager.health_manager import HealthManager

    capability_registry, tool_manager, brain = wiring
    health_manager = HealthManager(event_bus=event_bus, logger=logger)

    driver = GenerationModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
        event_bus=event_bus,
        health_manager=health_manager,
    )
    driver.start()

    assert health_manager.contains(MODULE_HEALTH_COMPONENT_ID)

    driver.stop()

    assert not health_manager.contains(MODULE_HEALTH_COMPONENT_ID)
