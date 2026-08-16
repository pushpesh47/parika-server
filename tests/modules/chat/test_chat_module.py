"""
Unit tests for the Chat Module.

Mirrors the shape of `tests/modules/web_search/test_web_search_module.py`:
the module driver is exercised against the real CapabilityRegistry
and HealthManager it integrates through.
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
from parika.modules.chat.driver import (
    CHAT_CAPABILITY_ID,
    MODULE_HEALTH_COMPONENT_ID,
    ChatModuleDriver,
)
from parika.modules.chat.manifest import CHAT_MODULE_ID, create_chat_module


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
    health_manager: HealthManager,
    logger: Logger,
) -> ChatModuleDriver:
    return ChatModuleDriver(
        capability_registry=capability_registry,
        logger=logger,
        health_manager=health_manager,
    )


class TestModuleLifecycle:
    def test_load_registers_llm_capability(
        self,
        module_manager: ModuleManager,
        module_driver: ChatModuleDriver,
        capability_registry: CapabilityRegistry,
    ) -> None:
        module_manager.register(create_chat_module(module_driver))
        module_manager.load(CHAT_MODULE_ID)

        assert capability_registry.contains(CHAT_CAPABILITY_ID)

        definition = capability_registry.get(CHAT_CAPABILITY_ID)
        assert definition.category is CapabilityCategory.LLM

        loaded = module_manager.get(CHAT_MODULE_ID)
        assert loaded.state is ModuleState.ACTIVE

    def test_load_registers_health_check(
        self,
        module_manager: ModuleManager,
        module_driver: ChatModuleDriver,
        health_manager: HealthManager,
    ) -> None:
        module_manager.register(create_chat_module(module_driver))
        module_manager.load(CHAT_MODULE_ID)

        assert health_manager.contains(MODULE_HEALTH_COMPONENT_ID)

        result = health_manager.run_check(MODULE_HEALTH_COMPONENT_ID)
        assert result.status is HealthStatus.HEALTHY

    def test_unload_unregisters_capability_and_health_check(
        self,
        module_manager: ModuleManager,
        module_driver: ChatModuleDriver,
        capability_registry: CapabilityRegistry,
        health_manager: HealthManager,
    ) -> None:
        module_manager.register(create_chat_module(module_driver))
        module_manager.load(CHAT_MODULE_ID)

        module_manager.unload(CHAT_MODULE_ID)

        assert not capability_registry.contains(CHAT_CAPABILITY_ID)
        assert not health_manager.contains(MODULE_HEALTH_COMPONENT_ID)

        with pytest.raises(CapabilityNotFoundError):
            capability_registry.get(CHAT_CAPABILITY_ID)

    def test_module_without_health_manager_still_starts(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        logger: Logger,
    ) -> None:
        driver = ChatModuleDriver(
            capability_registry=capability_registry,
            logger=logger,
        )
        module_manager.register(create_chat_module(driver))

        module_manager.load(CHAT_MODULE_ID)

        assert capability_registry.contains(CHAT_CAPABILITY_ID)

        module_manager.unload(CHAT_MODULE_ID)

        assert not capability_registry.contains(CHAT_CAPABILITY_ID)
