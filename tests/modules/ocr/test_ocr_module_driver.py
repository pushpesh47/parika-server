"""
Unit tests for OcrModuleDriver's registration/unregistration, mirroring
`tests/modules/vision/test_vision_module_driver.py`'s own wiring shape
- this Module previously had no dedicated registration/health test of
its own (only `test_ocr_tool_driver.py`, which exercises
`OcrToolDriver` directly, never `OcrModuleDriver`).
"""

from __future__ import annotations

import pytest

from parika.core.brain.brain import Brain
from parika.core.capability_executor.capability_executor import CapabilityExecutor
from parika.core.capability_registry.capability_category import CapabilityCategory
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.capability_resolver.capability_resolver import CapabilityResolver
from parika.core.configuration.configuration import Configuration
from parika.core.health_manager.health_manager import HealthManager
from parika.core.health_manager.health_status import HealthStatus
from parika.core.planner.planner import Planner
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.task_manager.task_manager import TaskManager
from parika.core.tool_manager.tool_manager import ToolManager
from parika.modules.ocr.module_driver import (
    _OCR_EXTENDED_TOOL_SPECS,
    EXTRACT_TEXT_CAPABILITY_ID,
    EXTRACT_TEXT_TOOL_ID,
    MODULE_HEALTH_COMPONENT_ID,
    PROVIDER_EXTRACT_TEXT_CAPABILITY_ID,
    OcrModuleDriver,
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

    driver = OcrModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
    )
    driver.start()

    assert capability_registry.contains(EXTRACT_TEXT_CAPABILITY_ID)
    assert capability_registry.contains(PROVIDER_EXTRACT_TEXT_CAPABILITY_ID)
    assert tool_manager.contains(EXTRACT_TEXT_TOOL_ID)

    for spec in _OCR_EXTENDED_TOOL_SPECS:
        assert capability_registry.contains(spec.tool_capability_id)
        assert tool_manager.contains(spec.tool_id)

    driver.stop()

    assert not capability_registry.contains(EXTRACT_TEXT_CAPABILITY_ID)
    assert not capability_registry.contains(PROVIDER_EXTRACT_TEXT_CAPABILITY_ID)
    assert not tool_manager.contains(EXTRACT_TEXT_TOOL_ID)

    for spec in _OCR_EXTENDED_TOOL_SPECS:
        assert not capability_registry.contains(spec.tool_capability_id)
        assert not tool_manager.contains(spec.tool_id)


def test_every_extended_capability_is_tool_category_with_affordance(
    wiring, logger
) -> None:
    capability_registry, tool_manager, brain = wiring

    driver = OcrModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
    )
    driver.start()

    for spec in _OCR_EXTENDED_TOOL_SPECS:
        capability = capability_registry.get(spec.tool_capability_id)
        assert capability.category is CapabilityCategory.TOOL
        assert "tool_affordance" in capability.metadata

    recognize_capability = capability_registry.get(PROVIDER_EXTRACT_TEXT_CAPABILITY_ID)
    assert recognize_capability.category is CapabilityCategory.OCR

    driver.stop()


def test_provider_capability_is_never_discoverable_as_tool_category(
    wiring, logger
) -> None:
    """
    Mirrors the Vision Module's own guarantee: only TOOL-category
    Capabilities are ever advertised to the model (Automatic
    Capability Discovery, `capability_context.discover_capabilities()`).
    Every extended Tool reuses the *same* `ocr.provider_extract_text`
    Provider Capability rather than registering its own.
    """

    capability_registry, tool_manager, brain = wiring

    driver = OcrModuleDriver(
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

    assert EXTRACT_TEXT_CAPABILITY_ID in discoverable_ids
    assert PROVIDER_EXTRACT_TEXT_CAPABILITY_ID not in discoverable_ids

    for spec in _OCR_EXTENDED_TOOL_SPECS:
        assert spec.tool_capability_id in discoverable_ids

    driver.stop()


def test_disabled_by_configuration_registers_nothing(logger, event_bus) -> None:
    configuration = Configuration()
    configuration._config = {"ocr": {"enabled": False}}  # noqa: SLF001

    capability_registry, tool_manager, brain = _wiring(configuration, logger, event_bus)

    driver = OcrModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
        configuration=configuration,
    )
    driver.start()

    assert not capability_registry.contains(EXTRACT_TEXT_CAPABILITY_ID)
    assert not capability_registry.contains(PROVIDER_EXTRACT_TEXT_CAPABILITY_ID)

    for spec in _OCR_EXTENDED_TOOL_SPECS:
        assert not capability_registry.contains(spec.tool_capability_id)
        assert not tool_manager.contains(spec.tool_id)


def test_health_check_reports_healthy(wiring, logger, event_bus) -> None:
    capability_registry, tool_manager, brain = wiring
    health_manager = HealthManager(event_bus=event_bus, logger=logger)

    driver = OcrModuleDriver(
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
