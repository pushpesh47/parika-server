"""
Unit tests for the Runtime Info Module.

Mirrors the shape of
`tests/modules/web_search/test_web_search_module.py`.
"""

from __future__ import annotations

import pytest

from parika.core.capability_registry.capability_category import (
    CapabilityCategory,
)
from parika.core.capability_registry.capability_registry import (
    CapabilityRegistry,
)
from parika.core.capability_registry.exceptions import (
    CapabilityNotFoundError,
)
from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.health_manager.health_manager import HealthManager
from parika.core.health_manager.health_status import HealthStatus
from parika.core.logger.logger import Logger
from parika.core.module_manager.module_manager import ModuleManager
from parika.core.module_manager.state import ModuleState
from parika.core.tool_manager.tool_manager import ToolManager
from parika.modules.runtime_info.driver import (
    MODULE_HEALTH_COMPONENT_ID,
    RuntimeInfoModuleDriver,
)
from parika.modules.runtime_info.manifest import (
    RUNTIME_INFO_MODULE_ID,
    create_runtime_info_module,
)
from parika.tools.runtime_info.manifest import (
    RUNTIME_INFO_CAPABILITY_ID,
    RUNTIME_INFO_TOOL_ID,
)


@pytest.fixture
def logger() -> Logger:
    return Logger(Configuration())


@pytest.fixture
def event_bus(logger: Logger) -> EventBus:
    return EventBus(logger=logger)


@pytest.fixture
def capability_registry(
    event_bus: EventBus,
    logger: Logger,
) -> CapabilityRegistry:
    return CapabilityRegistry(event_bus=event_bus, logger=logger)


@pytest.fixture
def tool_manager(event_bus: EventBus, logger: Logger) -> ToolManager:
    return ToolManager(event_bus=event_bus, logger=logger)


@pytest.fixture
def health_manager(event_bus: EventBus, logger: Logger) -> HealthManager:
    return HealthManager(event_bus=event_bus, logger=logger)


@pytest.fixture
def module_manager(event_bus: EventBus, logger: Logger) -> ModuleManager:
    return ModuleManager(
        configuration=Configuration(),
        event_bus=event_bus,
        logger=logger,
    )


@pytest.fixture
def module_driver(
    capability_registry: CapabilityRegistry,
    tool_manager: ToolManager,
    health_manager: HealthManager,
    logger: Logger,
) -> RuntimeInfoModuleDriver:
    return RuntimeInfoModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        logger=logger,
        health_manager=health_manager,
    )


class TestModuleLifecycle:
    def test_load_registers_capability_and_tool(
        self,
        module_manager: ModuleManager,
        module_driver: RuntimeInfoModuleDriver,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        module_manager.register(create_runtime_info_module(module_driver))
        module_manager.load(RUNTIME_INFO_MODULE_ID)

        assert capability_registry.contains(RUNTIME_INFO_CAPABILITY_ID)
        definition = capability_registry.get(RUNTIME_INFO_CAPABILITY_ID)
        assert definition.category is CapabilityCategory.TOOL

        assert tool_manager.contains(RUNTIME_INFO_TOOL_ID)

        loaded = module_manager.get(RUNTIME_INFO_MODULE_ID)
        assert loaded.state is ModuleState.ACTIVE

    def test_load_registers_health_check(
        self,
        module_manager: ModuleManager,
        module_driver: RuntimeInfoModuleDriver,
        health_manager: HealthManager,
    ) -> None:
        module_manager.register(create_runtime_info_module(module_driver))
        module_manager.load(RUNTIME_INFO_MODULE_ID)

        assert health_manager.contains(MODULE_HEALTH_COMPONENT_ID)
        result = health_manager.run_check(MODULE_HEALTH_COMPONENT_ID)
        assert result.status is HealthStatus.HEALTHY

    def test_unload_unregisters_capability_and_tool(
        self,
        module_manager: ModuleManager,
        module_driver: RuntimeInfoModuleDriver,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        health_manager: HealthManager,
    ) -> None:
        module_manager.register(create_runtime_info_module(module_driver))
        module_manager.load(RUNTIME_INFO_MODULE_ID)

        module_manager.unload(RUNTIME_INFO_MODULE_ID)

        assert not capability_registry.contains(RUNTIME_INFO_CAPABILITY_ID)
        assert not tool_manager.contains(RUNTIME_INFO_TOOL_ID)
        assert not health_manager.contains(MODULE_HEALTH_COMPONENT_ID)

        with pytest.raises(CapabilityNotFoundError):
            capability_registry.get(RUNTIME_INFO_CAPABILITY_ID)

    def test_module_without_health_manager_still_starts(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger: Logger,
    ) -> None:
        driver = RuntimeInfoModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
        )
        module_manager.register(create_runtime_info_module(driver))

        module_manager.load(RUNTIME_INFO_MODULE_ID)

        assert capability_registry.contains(RUNTIME_INFO_CAPABILITY_ID)

        module_manager.unload(RUNTIME_INFO_MODULE_ID)

        assert not capability_registry.contains(RUNTIME_INFO_CAPABILITY_ID)
