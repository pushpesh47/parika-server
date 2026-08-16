"""
Unit tests for the Web Search Module.

The module driver is exercised against the real CapabilityRegistry,
ToolManager, and HealthManager it integrates through, using a fake
SearchBackend/PageFetcher so no real network access is required.
"""

from __future__ import annotations

import pytest

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
from parika.core.tool_manager.exceptions import ToolNotFoundError
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.tool_manager import ToolManager
from parika.modules.web_search.driver import (
    MODULE_HEALTH_COMPONENT_ID,
    WebSearchModuleDriver,
)
from parika.modules.web_search.manifest import (
    WEB_SEARCH_MODULE_ID,
    create_web_search_module,
)
from parika.tools.web_search.manifest import (
    WEB_SEARCH_CAPABILITY_ID,
    WEB_SEARCH_TOOL_ID,
)
from parika.tools.web_search.page_content import PageContent
from parika.tools.web_search.search_result import SearchResult


class _FakeSearchBackend:
    def search(self, query: str, *, max_results: int) -> tuple:
        return (
            SearchResult(
                title="PARIKA",
                url="https://example.com/parika",
                snippet="An intelligence kernel.",
            ),
        )


class _FakePageFetcher:
    def fetch(self, url: str) -> PageContent:
        return PageContent(
            url=url,
            final_url=url,
            status_code=200,
            title="PARIKA",
            description="An intelligence kernel.",
            text="PARIKA text.",
            content_type="text/html",
            content_length=10,
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
def module_manager(
    event_bus: EventBus,
    logger: Logger,
) -> ModuleManager:
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
) -> WebSearchModuleDriver:
    return WebSearchModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        logger=logger,
        health_manager=health_manager,
        search_backend=_FakeSearchBackend(),
        page_fetcher=_FakePageFetcher(),
    )


class TestModuleLifecycle:
    def test_load_registers_capability_and_tool(
        self,
        module_manager: ModuleManager,
        module_driver: WebSearchModuleDriver,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        module = create_web_search_module(module_driver)
        module_manager.register(module)

        module_manager.load(WEB_SEARCH_MODULE_ID)

        assert capability_registry.contains(WEB_SEARCH_CAPABILITY_ID)
        assert tool_manager.contains(WEB_SEARCH_TOOL_ID)

        loaded = module_manager.get(WEB_SEARCH_MODULE_ID)
        assert loaded.state is ModuleState.ACTIVE

    def test_load_registers_health_check(
        self,
        module_manager: ModuleManager,
        module_driver: WebSearchModuleDriver,
        health_manager: HealthManager,
    ) -> None:
        module = create_web_search_module(module_driver)
        module_manager.register(module)
        module_manager.load(WEB_SEARCH_MODULE_ID)

        assert health_manager.contains(MODULE_HEALTH_COMPONENT_ID)

        result = health_manager.run_check(MODULE_HEALTH_COMPONENT_ID)
        assert result.status is HealthStatus.HEALTHY

    def test_unload_unregisters_capability_and_tool(
        self,
        module_manager: ModuleManager,
        module_driver: WebSearchModuleDriver,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        health_manager: HealthManager,
    ) -> None:
        module = create_web_search_module(module_driver)
        module_manager.register(module)
        module_manager.load(WEB_SEARCH_MODULE_ID)

        module_manager.unload(WEB_SEARCH_MODULE_ID)

        assert not capability_registry.contains(WEB_SEARCH_CAPABILITY_ID)
        assert not tool_manager.contains(WEB_SEARCH_TOOL_ID)
        assert not health_manager.contains(MODULE_HEALTH_COMPONENT_ID)

        with pytest.raises(CapabilityNotFoundError):
            capability_registry.get(WEB_SEARCH_CAPABILITY_ID)

        with pytest.raises(ToolNotFoundError):
            tool_manager.get(WEB_SEARCH_TOOL_ID)

    def test_module_without_health_manager_still_starts(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger: Logger,
    ) -> None:
        driver = WebSearchModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            search_backend=_FakeSearchBackend(),
            page_fetcher=_FakePageFetcher(),
        )
        module = create_web_search_module(driver)
        module_manager.register(module)

        module_manager.load(WEB_SEARCH_MODULE_ID)

        assert capability_registry.contains(WEB_SEARCH_CAPABILITY_ID)

        module_manager.unload(WEB_SEARCH_MODULE_ID)

        assert not capability_registry.contains(WEB_SEARCH_CAPABILITY_ID)


class TestConfigurationDrivenBackendSelection:
    """
    Priority 5: `[web_search]` configuration controls provider
    selection/failover and whether the module is active at all, while
    every existing caller that never supplies a `Configuration`, or
    that injects its own `search_backend` explicitly, is completely
    unaffected.
    """

    def test_no_configuration_defaults_to_google_only(
        self,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger: Logger,
    ) -> None:
        """
        No `Configuration` at all still means exactly one HTTP
        request per search, unaffected by this Tool now supporting
        several providers - just against the new default provider,
        Google, rather than DuckDuckGo (see
        `config.DEFAULT_PROVIDER`'s docstring).
        """

        driver = WebSearchModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
        )

        from parika.tools.web_search.search_backend_google import (
            GoogleHtmlSearchBackend,
        )

        assert isinstance(
            driver._tool_driver._search_backend,  # noqa: SLF001
            GoogleHtmlSearchBackend,
        )

    def test_full_defaults_toml_shaped_configuration_builds_a_failover(
        self,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger: Logger,
    ) -> None:
        """
        A `Configuration` shaped like the real, shipped
        `config/defaults.toml` (every implemented provider listed in
        `provider_order`) does fan out into a full failover chain,
        Google first - this is real production behavior once
        `Configuration.load()` has merged in `defaults.toml`, unlike
        the previous test's bare/unconfigured case.
        """

        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "web_search": {
                "default_provider": "google",
                "provider_order": [
                    "google",
                    "bing",
                    "duckduckgo",
                    "mojeek",
                    "qwant",
                    "google_cse",
                ],
            }
        }

        driver = WebSearchModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            configuration=configuration,
        )

        from parika.tools.web_search.search_backend_failover import (
            FailoverSearchBackend,
        )

        backend = driver._tool_driver._search_backend  # noqa: SLF001
        assert isinstance(backend, FailoverSearchBackend)
        assert [name for name, _ in backend._backends][0] == "google"  # noqa: SLF001

    def test_only_google_configured_builds_a_single_unwrapped_backend(
        self,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger: Logger,
    ) -> None:
        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "web_search": {
                "default_provider": "google",
                "provider_order": ["google"],
            }
        }

        driver = WebSearchModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            configuration=configuration,
        )

        from parika.tools.web_search.search_backend_google import (
            GoogleHtmlSearchBackend,
        )

        assert isinstance(
            driver._tool_driver._search_backend,  # noqa: SLF001
            GoogleHtmlSearchBackend,
        )

    def test_explicit_search_backend_overrides_configuration(
        self,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger: Logger,
    ) -> None:
        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "web_search": {
                "default_provider": "bing",
                "provider_order": ["bing"],
            }
        }

        fake_backend = _FakeSearchBackend()
        driver = WebSearchModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            configuration=configuration,
            search_backend=fake_backend,
        )

        assert driver._tool_driver._search_backend is fake_backend  # noqa: SLF001

    def test_multiple_configured_providers_build_a_failover_backend(
        self,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger: Logger,
    ) -> None:
        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "web_search": {
                "default_provider": "duckduckgo",
                "provider_order": ["duckduckgo", "bing", "google"],
            }
        }

        driver = WebSearchModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            configuration=configuration,
        )

        from parika.tools.web_search.search_backend_failover import (
            FailoverSearchBackend,
        )

        assert isinstance(
            driver._tool_driver._search_backend,  # noqa: SLF001
            FailoverSearchBackend,
        )

    def test_google_cse_without_credentials_is_skipped(
        self,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger: Logger,
    ) -> None:
        """
        `google_cse` is registered in every default `provider_order`
        but must never be attempted without credentials - it is
        skipped automatically, falling back to the next provider.
        """

        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "web_search": {
                "default_provider": "google_cse",
                "provider_order": ["google_cse", "bing"],
            }
        }

        driver = WebSearchModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            configuration=configuration,
        )

        from parika.tools.web_search.search_backend_bing import (
            BingHtmlSearchBackend,
        )

        assert isinstance(
            driver._tool_driver._search_backend,  # noqa: SLF001
            BingHtmlSearchBackend,
        )

    def test_google_cse_with_credentials_is_used(
        self,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger: Logger,
    ) -> None:
        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "web_search": {
                "default_provider": "google_cse",
                "provider_order": ["google_cse"],
                "google_cse": {
                    "api_key": "test-key",
                    "search_engine_id": "test-cx",
                },
            }
        }

        driver = WebSearchModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            configuration=configuration,
        )

        from parika.tools.web_search.search_backend_google_cse import (
            GoogleCseSearchBackend,
        )

        assert isinstance(
            driver._tool_driver._search_backend,  # noqa: SLF001
            GoogleCseSearchBackend,
        )

    def test_disabled_by_configuration_never_registers(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger: Logger,
    ) -> None:
        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "web_search": {"enabled": False}
        }

        driver = WebSearchModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            configuration=configuration,
            search_backend=_FakeSearchBackend(),
            page_fetcher=_FakePageFetcher(),
        )
        module = create_web_search_module(driver)
        module_manager.register(module)

        module_manager.load(WEB_SEARCH_MODULE_ID)

        assert not capability_registry.contains(WEB_SEARCH_CAPABILITY_ID)
        assert not tool_manager.contains(WEB_SEARCH_TOOL_ID)

        # Unloading a never-registered module is a clean no-op too.
        module_manager.unload(WEB_SEARCH_MODULE_ID)


class TestToolExecutionThroughModule:
    def test_registered_tool_executes_via_tool_manager(
        self,
        module_manager: ModuleManager,
        module_driver: WebSearchModuleDriver,
        tool_manager: ToolManager,
    ) -> None:
        module = create_web_search_module(module_driver)
        module_manager.register(module)
        module_manager.load(WEB_SEARCH_MODULE_ID)

        response = tool_manager.execute(
            WEB_SEARCH_TOOL_ID,
            ToolRequest(arguments={"query": "parika"}),
        )

        assert response.attributes["query"] == "parika"
        assert response.result[0]["title"] == "PARIKA"
