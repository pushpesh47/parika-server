"""
End-to-end integration tests for the complete execution pipeline,
exercised against every Phase 2 Tool:

    Brain -> Planner -> TaskManager -> CapabilityExecutor ->
    ToolManager -> <Tool> -> (local filesystem | fake network)

Mirrors `tests/integration/test_web_search_pipeline.py`'s shape and
intent exactly: a single Goal carrying a capability id and arguments,
proving that Planner selects the correct Tool purely by
`capability_id`, with zero Core changes, for Filesystem, Weather,
Currency, and News - the same way it already does for Web Search and
Runtime Info.
"""

from __future__ import annotations

import json

import pytest

from parika.core.brain.brain import Brain
from parika.core.brain.brain_request import BrainRequest
from parika.core.capability_executor.capability_executor import (
    CapabilityExecutor,
)
from parika.core.capability_registry.capability_registry import (
    CapabilityRegistry,
)
from parika.core.capability_resolver.capability_resolver import (
    CapabilityResolver,
)
from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.module_manager.module_manager import ModuleManager
from parika.core.planner.goal import Goal
from parika.core.planner.planner import Planner
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.task_manager.task_manager import TaskManager
from parika.core.task_manager.task_status import TaskStatus
from parika.core.tool_manager.tool_manager import ToolManager
from parika.modules.currency.driver import CurrencyModuleDriver
from parika.modules.currency.manifest import (
    CURRENCY_MODULE_ID,
    create_currency_module,
)
from parika.modules.filesystem.driver import FilesystemModuleDriver
from parika.modules.filesystem.manifest import (
    FILESYSTEM_MODULE_ID,
    create_filesystem_module,
)
from parika.modules.news.driver import NewsModuleDriver
from parika.modules.news.manifest import NEWS_MODULE_ID, create_news_module
from parika.modules.weather.driver import WeatherModuleDriver
from parika.modules.weather.manifest import (
    WEATHER_MODULE_ID,
    create_weather_module,
)
from parika.tools.currency.transport import HttpResponse as CurrencyHttpResponse
from parika.tools.news.transport import HttpResponse as NewsHttpResponse
from parika.tools.weather.transport import HttpResponse as WeatherHttpResponse

RSS_FEED = """<?xml version="1.0"?><rss version="2.0"><channel>
<title>Test Feed</title>
<item><title>Headline One</title><link>https://news.example/1</link>
<description>Summary.</description>
<pubDate>Wed, 30 Jul 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""


class _FakeWeatherTransport:
    def get(self, url: str, *, timeout: float) -> WeatherHttpResponse:
        if "geocoding-api" in url:
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
                {
                    "timezone": "Asia/Kolkata",
                    "current": {
                        "time": "2026-07-30T12:00",
                        "temperature_2m": 27.0,
                        "relative_humidity_2m": 55,
                        "apparent_temperature": 29.0,
                        "precipitation": 0.0,
                        "weather_code": 0,
                        "wind_speed_10m": 8.0,
                        "wind_direction_10m": 90,
                        "is_day": 1,
                    },
                }
            ).encode()

        return WeatherHttpResponse(status_code=200, url=url, headers={}, body=body)


class _FakeCurrencyTransport:
    def get(self, url: str, *, timeout: float) -> CurrencyHttpResponse:
        body = json.dumps(
            {"amount": 1.0, "base": "USD", "date": "2026-07-30", "rates": {"EUR": 0.9}}
        ).encode()

        return CurrencyHttpResponse(status_code=200, url=url, headers={}, body=body)


class _FakeNewsTransport:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get(self, url: str, *, timeout: float) -> NewsHttpResponse:
        self.calls.append(url)

        return NewsHttpResponse(
            status_code=200, url=url, headers={}, body=RSS_FEED.encode()
        )


class Pipeline:
    """Bundles the full, real Core stack plus every Phase 2 Module."""

    def __init__(self, *, filesystem_allowed_root: str) -> None:
        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "filesystem": {
                "enabled": True,
                "allowed_roots": [filesystem_allowed_root],
                "allow_write": True,
                "allow_delete": True,
            }
        }

        logger = Logger(configuration)
        event_bus = EventBus(logger=logger)

        capability_registry = CapabilityRegistry(
            event_bus=event_bus, logger=logger
        )
        capability_resolver = CapabilityResolver(
            capability_registry=capability_registry, logger=logger
        )
        resource_manager = ResourceManager(
            configuration=configuration, logger=logger
        )
        policy_engine = PolicyEngine(event_bus=event_bus, logger=logger)
        provider_manager = ProviderManager(event_bus=event_bus, logger=logger)
        tool_manager = ToolManager(event_bus=event_bus, logger=logger)
        module_manager = ModuleManager(
            configuration=configuration, event_bus=event_bus, logger=logger
        )

        capability_executor = CapabilityExecutor(
            event_bus=event_bus,
            logger=logger,
            tool_manager=tool_manager,
            provider_manager=provider_manager,
        )
        self.task_manager = TaskManager(
            event_bus=event_bus,
            logger=logger,
            capability_executor=capability_executor,
        )
        planner = Planner(
            capability_resolver=capability_resolver,
            resource_manager=resource_manager,
            policy_engine=policy_engine,
            provider_manager=provider_manager,
            tool_manager=tool_manager,
            logger=logger,
            configuration=configuration,
        )
        self.brain = Brain(
            planner=planner, task_manager=self.task_manager, logger=logger
        )

        self.module_manager = module_manager
        self.capability_registry = capability_registry

        filesystem_driver = FilesystemModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            configuration=configuration,
        )
        module_manager.register(create_filesystem_module(filesystem_driver))
        module_manager.load(FILESYSTEM_MODULE_ID)

        self.weather_transport = _FakeWeatherTransport()
        weather_driver = WeatherModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            transport=self.weather_transport,
        )
        module_manager.register(create_weather_module(weather_driver))
        module_manager.load(WEATHER_MODULE_ID)

        self.currency_transport = _FakeCurrencyTransport()
        currency_driver = CurrencyModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            transport=self.currency_transport,
        )
        module_manager.register(create_currency_module(currency_driver))
        module_manager.load(CURRENCY_MODULE_ID)

        self.news_transport = _FakeNewsTransport()
        news_driver = NewsModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            transport=self.news_transport,
        )
        module_manager.register(create_news_module(news_driver))
        module_manager.load(NEWS_MODULE_ID)


@pytest.fixture
def pipeline(tmp_path) -> Pipeline:  # noqa: ANN001
    return Pipeline(filesystem_allowed_root=str(tmp_path))


class TestFilesystemThroughPlanner:
    def test_write_then_read_via_goals(self, pipeline: Pipeline, tmp_path) -> None:  # noqa: ANN001
        target = str(tmp_path / "note.txt")

        write_goal = Goal(
            id="fs-write",
            capability_id="filesystem.write",
            inputs={"path": target, "content": "hello from PARIKA"},
        )
        response = pipeline.brain.handle(BrainRequest(goals=(write_goal,)))
        assert response.succeeded

        read_goal = Goal(
            id="fs-read",
            capability_id="filesystem.read",
            inputs={"path": target},
        )
        response = pipeline.brain.handle(BrainRequest(goals=(read_goal,)))
        assert response.succeeded

        result = response.results[0]
        assert result.status is TaskStatus.COMPLETED
        tool_response = result.response.outputs["result"]
        assert tool_response.result["content"] == "hello from PARIKA"

    def test_write_outside_allowed_root_fails_the_goal(
        self, pipeline: Pipeline
    ) -> None:
        """
        Mutating operations (write/mkdir/copy-destination/move/delete)
        remain confined to `allowed_roots`, even though reads outside
        `allowed_roots` are now permitted in READ ONLY mode -- see
        `parika/tools/filesystem/security.py`'s `PathSecurity.resolve()`.
        """

        goal = Goal(
            id="fs-escape",
            capability_id="filesystem.write",
            inputs={"path": "/etc/parika-escape-attempt.txt", "content": "x"},
        )
        response = pipeline.brain.handle(BrainRequest(goals=(goal,)))

        assert not response.succeeded
        assert response.results[0].status is TaskStatus.FAILED

    def test_read_outside_allowed_root_succeeds(self, pipeline: Pipeline) -> None:
        """
        Reads are permitted outside `allowed_roots`, subject to real
        OS-level file permissions.
        """

        goal = Goal(
            id="fs-read-outside",
            capability_id="filesystem.read",
            inputs={"path": "/etc/hostname"},
        )
        response = pipeline.brain.handle(BrainRequest(goals=(goal,)))

        assert response.succeeded


class TestWeatherThroughPlanner:
    def test_current_weather_via_goal(self, pipeline: Pipeline) -> None:
        goal = Goal(
            id="weather-1",
            capability_id="weather.current",
            inputs={"location": "Bengaluru"},
        )
        response = pipeline.brain.handle(BrainRequest(goals=(goal,)))

        assert response.succeeded
        tool_response = response.results[0].response.outputs["result"]
        assert tool_response.result["location"] == "Bengaluru"
        assert tool_response.result["temperature"] == 27.0


class TestCurrencyThroughPlanner:
    def test_exchange_rate_via_goal(self, pipeline: Pipeline) -> None:
        goal = Goal(
            id="currency-1",
            capability_id="currency.exchange_rate",
            inputs={"base": "USD", "quote": "EUR"},
        )
        response = pipeline.brain.handle(BrainRequest(goals=(goal,)))

        assert response.succeeded
        tool_response = response.results[0].response.outputs["result"]
        assert tool_response.result["rate"] == 0.9


class TestNewsThroughPlanner:
    def test_latest_news_via_goal(self, pipeline: Pipeline) -> None:
        goal = Goal(id="news-1", capability_id="news.latest", inputs={})
        response = pipeline.brain.handle(BrainRequest(goals=(goal,)))

        assert response.succeeded
        tool_response = response.results[0].response.outputs["result"]
        assert tool_response.result[0]["title"] == "Headline One"


class TestNoHardcodedRouting:
    def test_all_new_capabilities_are_registered_and_resolvable(
        self, pipeline: Pipeline
    ) -> None:
        """
        Every new capability must be independently registered in
        CapabilityRegistry - proving Planner's generic
        `capability_id in tool.capabilities` matching is all that is
        needed to select the right Tool, with no
        `if "weather"`/`if "currency"`/etc. shortcut anywhere.
        """

        module = pipeline.module_manager.get(FILESYSTEM_MODULE_ID)
        assert module.state.value == "active"

        expected = {
            "filesystem.read",
            "filesystem.write",
            "filesystem.list",
            "filesystem.search",
            "filesystem.copy",
            "filesystem.move",
            "filesystem.delete",
            "filesystem.mkdir",
            "filesystem.exists",
            "filesystem.info",
            "filesystem.walk",
            "filesystem.permissions",
            "filesystem.watch",
            "weather.current",
            "weather.forecast",
            "currency.exchange_rate",
            "currency.convert",
            "news.latest",
            "news.search",
            "news.topic",
        }

        for capability_id in expected:
            assert pipeline.capability_registry.contains(capability_id)
            assert pipeline.capability_registry.get(capability_id).enabled
