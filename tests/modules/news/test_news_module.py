"""
Unit tests for the News Module.
"""

from __future__ import annotations

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
from parika.modules.news.driver import MODULE_HEALTH_COMPONENT_ID, NewsModuleDriver
from parika.modules.news.manifest import NEWS_MODULE_ID, create_news_module
from parika.tools.news.manifest import (
    NEWS_CAPABILITY_LATEST,
    NEWS_CAPABILITY_SEARCH,
    NEWS_CAPABILITY_TOPIC,
    NEWS_TOOL_ID_LATEST,
    NEWS_TOOL_ID_SEARCH,
    NEWS_TOOL_ID_TOPIC,
)
from parika.tools.news.transport import HttpResponse

FEED = """<?xml version="1.0"?><rss version="2.0"><channel><title>A</title>
<item><title>Headline</title><link>https://a.example/1</link>
<description>d</description>
<pubDate>Thu, 30 Jul 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""


class _FakeTransport:
    def get(self, url: str, *, timeout: float) -> HttpResponse:
        return HttpResponse(status_code=200, url=url, headers={}, body=FEED.encode())


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
    def test_load_registers_all_three_capabilities_and_tools(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        health_manager: HealthManager,
        logger: Logger,
    ) -> None:
        driver = NewsModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            health_manager=health_manager,
            transport=_FakeTransport(),
        )
        module_manager.register(create_news_module(driver))
        module_manager.load(NEWS_MODULE_ID)

        assert capability_registry.contains(NEWS_CAPABILITY_LATEST)
        assert capability_registry.contains(NEWS_CAPABILITY_SEARCH)
        assert capability_registry.contains(NEWS_CAPABILITY_TOPIC)
        assert tool_manager.contains(NEWS_TOOL_ID_LATEST)
        assert tool_manager.contains(NEWS_TOOL_ID_SEARCH)
        assert tool_manager.contains(NEWS_TOOL_ID_TOPIC)

        loaded = module_manager.get(NEWS_MODULE_ID)
        assert loaded.state is ModuleState.ACTIVE

    def test_load_registers_health_check(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        health_manager: HealthManager,
        logger: Logger,
    ) -> None:
        driver = NewsModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            health_manager=health_manager,
            transport=_FakeTransport(),
        )
        module_manager.register(create_news_module(driver))
        module_manager.load(NEWS_MODULE_ID)

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
        driver = NewsModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            transport=_FakeTransport(),
        )
        module_manager.register(create_news_module(driver))
        module_manager.load(NEWS_MODULE_ID)
        module_manager.unload(NEWS_MODULE_ID)

        assert not capability_registry.contains(NEWS_CAPABILITY_LATEST)
        assert not capability_registry.contains(NEWS_CAPABILITY_SEARCH)
        assert not capability_registry.contains(NEWS_CAPABILITY_TOPIC)

    def test_disabled_by_configuration_never_registers(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger: Logger,
    ) -> None:
        configuration = Configuration()
        configuration._config = {"news": {"enabled": False}}  # noqa: SLF001

        driver = NewsModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            configuration=configuration,
            transport=_FakeTransport(),
        )
        module_manager.register(create_news_module(driver))
        module_manager.load(NEWS_MODULE_ID)

        assert not capability_registry.contains(NEWS_CAPABILITY_LATEST)


class TestToolExecutionThroughModule:
    def test_latest_executes(
        self,
        module_manager: ModuleManager,
        tool_manager: ToolManager,
        capability_registry: CapabilityRegistry,
        logger: Logger,
    ) -> None:
        driver = NewsModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            transport=_FakeTransport(),
        )
        module_manager.register(create_news_module(driver))
        module_manager.load(NEWS_MODULE_ID)

        response = tool_manager.execute(
            NEWS_TOOL_ID_LATEST, ToolRequest(arguments={})
        )

        assert response.result[0]["title"] == "Headline"
