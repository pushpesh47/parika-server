"""
Unit tests for VideoModuleDriver's registration/unregistration,
mirroring `tests/modules/ocr/test_ocr_module_driver.py`'s own wiring
shape.
"""

from __future__ import annotations

import pytest

from parika.core.brain.brain import Brain
from parika.core.capability_executor.capability_executor import CapabilityExecutor
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.capability_resolver.capability_resolver import CapabilityResolver
from parika.core.configuration.configuration import Configuration
from parika.core.planner.planner import Planner
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.task_manager.task_manager import TaskManager
from parika.core.tool_manager.tool_manager import ToolManager
from parika.modules.video.module_driver import (
    MODULE_HEALTH_COMPONENT_ID,
    _VIDEO_TOOL_SPECS,
    VideoModuleDriver,
)


def _wiring(configuration: Configuration, logger, event_bus):
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


@pytest.fixture()
def wiring(logger, event_bus, configuration):
    return _wiring(configuration, logger, event_bus)


def test_start_registers_every_capability_and_tool(wiring, logger) -> None:
    capability_registry, tool_manager, brain = wiring

    driver = VideoModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
    )
    driver.start()

    assert len(_VIDEO_TOOL_SPECS) == 30

    for spec in _VIDEO_TOOL_SPECS:
        assert capability_registry.contains(spec.tool_capability_id)
        assert tool_manager.contains(spec.tool_id)

        if spec.provider_capability_id is not None:
            assert capability_registry.contains(spec.provider_capability_id)

    driver.stop()

    for spec in _VIDEO_TOOL_SPECS:
        assert not capability_registry.contains(spec.tool_capability_id)
        assert not tool_manager.contains(spec.tool_id)

        if spec.provider_capability_id is not None:
            assert not capability_registry.contains(spec.provider_capability_id)


def test_disabled_configuration_skips_registration(logger, event_bus, configuration) -> None:
    configuration._config = {"video": {"enabled": False}}  # noqa: SLF001
    capability_registry, tool_manager, brain = _wiring(configuration, logger, event_bus)

    driver = VideoModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
        configuration=configuration,
    )
    driver.start()

    for spec in _VIDEO_TOOL_SPECS:
        assert not capability_registry.contains(spec.tool_capability_id)

    driver.stop()


def test_health_check_reports_healthy(wiring, logger) -> None:
    from parika.core.health_manager.health_status import HealthStatus

    capability_registry, tool_manager, brain = wiring

    driver = VideoModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
    )

    assert driver._check_health().status == HealthStatus.HEALTHY  # noqa: SLF001


def test_provider_capabilities_use_vision_category(wiring, logger) -> None:
    from parika.core.capability_registry.capability_category import CapabilityCategory

    capability_registry, tool_manager, brain = wiring

    driver = VideoModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
    )
    driver.start()

    provider_ids = [spec.provider_capability_id for spec in _VIDEO_TOOL_SPECS if spec.provider_capability_id]
    assert len(provider_ids) == 6

    for provider_id in provider_ids:
        definition = capability_registry.get(provider_id)
        assert definition.category == CapabilityCategory.VISION

    driver.stop()
