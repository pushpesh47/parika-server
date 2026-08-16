"""
Unit tests for the Weather Module.
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
from parika.modules.weather.driver import (
    MODULE_HEALTH_COMPONENT_ID,
    WeatherModuleDriver,
)
from parika.modules.weather.manifest import (
    WEATHER_MODULE_ID,
    create_weather_module,
)
from parika.tools.weather.manifest import (
    WEATHER_CAPABILITY_CURRENT,
    WEATHER_CAPABILITY_FORECAST,
    WEATHER_TOOL_ID_CURRENT,
    WEATHER_TOOL_ID_FORECAST,
)
from parika.tools.weather.transport import HttpResponse


class _FakeTransport:
    def get(self, url: str, *, timeout: float) -> HttpResponse:
        if "geocoding" in url:
            body = json.dumps(
                {
                    "results": [
                        {
                            "name": "Bengaluru",
                            "latitude": 12.97,
                            "longitude": 77.59,
                            "country": "India",
                            "timezone": "Asia/Kolkata",
                        }
                    ]
                }
            ).encode()
        else:
            body = json.dumps(
                {"timezone": "Asia/Kolkata", "current": {"temperature_2m": 25}}
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
        driver = WeatherModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            health_manager=health_manager,
            transport=_FakeTransport(),
        )
        module_manager.register(create_weather_module(driver))
        module_manager.load(WEATHER_MODULE_ID)

        assert capability_registry.contains(WEATHER_CAPABILITY_CURRENT)
        assert capability_registry.contains(WEATHER_CAPABILITY_FORECAST)
        assert tool_manager.contains(WEATHER_TOOL_ID_CURRENT)
        assert tool_manager.contains(WEATHER_TOOL_ID_FORECAST)

        loaded = module_manager.get(WEATHER_MODULE_ID)
        assert loaded.state is ModuleState.ACTIVE

    def test_load_registers_health_check(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        health_manager: HealthManager,
        logger: Logger,
    ) -> None:
        driver = WeatherModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            health_manager=health_manager,
            transport=_FakeTransport(),
        )
        module_manager.register(create_weather_module(driver))
        module_manager.load(WEATHER_MODULE_ID)

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
        driver = WeatherModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            transport=_FakeTransport(),
        )
        module_manager.register(create_weather_module(driver))
        module_manager.load(WEATHER_MODULE_ID)
        module_manager.unload(WEATHER_MODULE_ID)

        assert not capability_registry.contains(WEATHER_CAPABILITY_CURRENT)
        assert not capability_registry.contains(WEATHER_CAPABILITY_FORECAST)
        assert not tool_manager.contains(WEATHER_TOOL_ID_CURRENT)
        assert not tool_manager.contains(WEATHER_TOOL_ID_FORECAST)

    def test_disabled_by_configuration_never_registers(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger: Logger,
    ) -> None:
        configuration = Configuration()
        configuration._config = {"weather": {"enabled": False}}  # noqa: SLF001

        driver = WeatherModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            configuration=configuration,
            transport=_FakeTransport(),
        )
        module_manager.register(create_weather_module(driver))
        module_manager.load(WEATHER_MODULE_ID)

        assert not capability_registry.contains(WEATHER_CAPABILITY_CURRENT)


class TestToolExecutionThroughModule:
    def test_current_weather_executes(
        self,
        module_manager: ModuleManager,
        tool_manager: ToolManager,
        capability_registry: CapabilityRegistry,
        logger: Logger,
    ) -> None:
        driver = WeatherModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            transport=_FakeTransport(),
        )
        module_manager.register(create_weather_module(driver))
        module_manager.load(WEATHER_MODULE_ID)

        response = tool_manager.execute(
            WEATHER_TOOL_ID_CURRENT,
            ToolRequest(arguments={"location": "Bengaluru"}),
        )

        assert response.result["location"] == "Bengaluru"
