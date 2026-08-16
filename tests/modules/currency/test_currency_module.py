"""
Unit tests for the Currency Module.
"""

from __future__ import annotations

import json

import pytest

from parika.core.capability_registry.capability_registry import (
    CapabilityRegistry,
)
from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.health_manager.health_manager import HealthManager
from parika.core.health_manager.health_status import HealthStatus
from parika.core.logger.logger import Logger
from parika.core.module_manager.module_manager import ModuleManager
from parika.core.module_manager.state import ModuleState
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.tool_manager import ToolManager
from parika.modules.currency.driver import (
    MODULE_HEALTH_COMPONENT_ID,
    CurrencyModuleDriver,
)
from parika.modules.currency.manifest import (
    CURRENCY_MODULE_ID,
    create_currency_module,
)
from parika.tools.currency.manifest import (
    CURRENCY_CAPABILITY_CONVERT,
    CURRENCY_CAPABILITY_EXCHANGE_RATE,
    CURRENCY_TOOL_ID_CONVERT,
    CURRENCY_TOOL_ID_EXCHANGE_RATE,
)
from parika.tools.currency.transport import HttpResponse


class _FakeTransport:
    def get(self, url: str, *, timeout: float) -> HttpResponse:
        body = json.dumps(
            {"amount": 1.0, "base": "USD", "rates": {"EUR": 0.9}}
        ).encode()
        return HttpResponse(status_code=200, url=url, headers={}, body=body)


@pytest.fixture
def logger() -> Logger:
    return Logger(Configuration())


@pytest.fixture
def event_bus(logger: Logger) -> EventBus:
    return EventBus(logger=logger)


@pytest.fixture
def capability_registry(
    event_bus: EventBus, logger: Logger
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
        configuration=Configuration(), event_bus=event_bus, logger=logger
    )


class TestModuleLifecycle:
    def test_load_registers_both_capabilities_and_tools(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        health_manager: HealthManager,
        logger: Logger,
    ) -> None:
        driver = CurrencyModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            health_manager=health_manager,
            transport=_FakeTransport(),
        )
        module_manager.register(create_currency_module(driver))
        module_manager.load(CURRENCY_MODULE_ID)

        assert capability_registry.contains(CURRENCY_CAPABILITY_EXCHANGE_RATE)
        assert capability_registry.contains(CURRENCY_CAPABILITY_CONVERT)
        assert tool_manager.contains(CURRENCY_TOOL_ID_EXCHANGE_RATE)
        assert tool_manager.contains(CURRENCY_TOOL_ID_CONVERT)

        loaded = module_manager.get(CURRENCY_MODULE_ID)
        assert loaded.state is ModuleState.ACTIVE

    def test_load_registers_health_check(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        health_manager: HealthManager,
        logger: Logger,
    ) -> None:
        driver = CurrencyModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            health_manager=health_manager,
            transport=_FakeTransport(),
        )
        module_manager.register(create_currency_module(driver))
        module_manager.load(CURRENCY_MODULE_ID)

        assert health_manager.contains(MODULE_HEALTH_COMPONENT_ID)
        result = health_manager.run_check(MODULE_HEALTH_COMPONENT_ID)
        assert result.status is HealthStatus.HEALTHY

    def test_unload_unregisters_everything(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger: Logger,
    ) -> None:
        driver = CurrencyModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            transport=_FakeTransport(),
        )
        module_manager.register(create_currency_module(driver))
        module_manager.load(CURRENCY_MODULE_ID)
        module_manager.unload(CURRENCY_MODULE_ID)

        assert not capability_registry.contains(CURRENCY_CAPABILITY_EXCHANGE_RATE)
        assert not capability_registry.contains(CURRENCY_CAPABILITY_CONVERT)

    def test_disabled_by_configuration_never_registers(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger: Logger,
    ) -> None:
        configuration = Configuration()
        configuration._config = {"currency": {"enabled": False}}  # noqa: SLF001

        driver = CurrencyModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            configuration=configuration,
            transport=_FakeTransport(),
        )
        module_manager.register(create_currency_module(driver))
        module_manager.load(CURRENCY_MODULE_ID)

        assert not capability_registry.contains(CURRENCY_CAPABILITY_EXCHANGE_RATE)


class TestToolExecutionThroughModule:
    def test_exchange_rate_executes(
        self,
        module_manager: ModuleManager,
        tool_manager: ToolManager,
        capability_registry: CapabilityRegistry,
        logger: Logger,
    ) -> None:
        driver = CurrencyModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            transport=_FakeTransport(),
        )
        module_manager.register(create_currency_module(driver))
        module_manager.load(CURRENCY_MODULE_ID)

        response = tool_manager.execute(
            CURRENCY_TOOL_ID_EXCHANGE_RATE,
            ToolRequest(arguments={"base": "USD", "quote": "EUR"}),
        )

        assert response.result["rate"] == 0.9

    def test_explicit_rate_backend_override(
        self,
        module_manager: ModuleManager,
        tool_manager: ToolManager,
        capability_registry: CapabilityRegistry,
        logger: Logger,
    ) -> None:
        class _FakeRateBackend:
            def get_rate(self, base: str, quote: str) -> float:
                return 42.0

        driver = CurrencyModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            rate_backend=_FakeRateBackend(),
        )
        module_manager.register(create_currency_module(driver))
        module_manager.load(CURRENCY_MODULE_ID)

        response = tool_manager.execute(
            CURRENCY_TOOL_ID_EXCHANGE_RATE,
            ToolRequest(arguments={"base": "USD", "quote": "EUR"}),
        )

        assert response.result["rate"] == 42.0
