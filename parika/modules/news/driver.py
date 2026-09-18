"""
PARIKA News Module - Driver

Implements the ModuleDriver contract for the News Module.

NewsModuleDriver owns the module's runtime lifecycle: starting
registers the `news.latest`, `news.search`, and `news.topic`
Capabilities with CapabilityRegistry and their supporting Tools with
ToolManager; stopping unregisters all six. When a HealthManager is
supplied, the module also registers a health check for itself.

NewsModuleDriver never bypasses the architecture: it interacts with
CapabilityRegistry and ToolManager exclusively through their public
APIs and never executes capabilities or tools directly itself.
"""

from __future__ import annotations

from parika.core.implementation_registry.implementation_registry import (
    ImplementationRegistry,
)
from parika.core.implementation_registry.implementation import (
    ImplementationSource,
    ImplementationStatus,
    ImplementationMetadata,
)
from parika.core.capability_registry.capability_category import (
    CapabilityCategory,
)
from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)
from parika.core.capability_registry.capability_registry import (
    CapabilityRegistry,
)
from parika.core.configuration.configuration import Configuration
from parika.core.health_manager.health_check_result import (
    HealthCheckResult,
)
from parika.core.health_manager.health_manager import HealthManager
from parika.core.health_manager.health_status import HealthStatus
from parika.core.logger.logger import Logger
from parika.core.module_manager.driver import ModuleDriver
from parika.core.tool_manager.tool_manager import ToolManager
from parika.tools.news.config import load_news_config
from parika.tools.news.driver import NewsToolDriver
from parika.tools.news.manifest import (
    NEWS_CAPABILITY_LATEST,
    NEWS_CAPABILITY_SEARCH,
    NEWS_CAPABILITY_TOPIC,
    NEWS_TOOL_ID_LATEST,
    NEWS_TOOL_ID_SEARCH,
    NEWS_TOOL_ID_TOPIC,
    NEWS_TOOL_AFFORDANCES,
    NewsMode,
    create_news_latest_tool,
    create_news_search_tool,
    create_news_topic_tool,
)
from parika.tools.news.transport import HttpTransport, UrllibHttpTransport

MODULE_HEALTH_COMPONENT_ID = "module.news"


class NewsModuleDriver(ModuleDriver):
    """
    Runtime driver for the News Module.
    """

    def __init__(
        self,
        *,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger: Logger,
        health_manager: HealthManager | None = None,
        configuration: Configuration | None = None,
        transport: HttpTransport | None = None,
        implementation_registry: ImplementationRegistry | None = None,
    ) -> None:
        """
        Initialize the NewsModuleDriver.

        Args:
            capability_registry:
                Registry used to register/unregister
                `news.latest`/`news.search`/`news.topic`.

            tool_manager:
                Manager used to register/unregister the News Tools.

            logger:
                PARIKA Logger component.

            health_manager:
                Optional HealthManager.

            configuration:
                Optional Core `Configuration`, used to read the
                `[news]` section (feed lists, timeouts). When
                omitted (`None`), the built-in curated feed list is
                used (see `parika.tools.news.feed_sources`).

            transport:
                Optional HttpTransport override, primarily for tests.
                Defaults to `UrllibHttpTransport`.

            implementation_registry:
                Optional ImplementationRegistry for registering native
                capability implementations. When supplied, a
                PARIKA_NATIVE implementation is registered for each
                news capability.
        """

        self._capability_registry = capability_registry
        self._tool_manager = tool_manager
        self._health_manager = health_manager
        self._logger = logger.get_logger(__name__)
        self._implementation_registry = implementation_registry

        news_config = load_news_config(configuration)
        self._enabled = news_config.enabled

        resolved_transport = transport or UrllibHttpTransport()

        def _build(mode: NewsMode) -> NewsToolDriver:
            return NewsToolDriver(
                mode,
                transport=resolved_transport,
                latest_feeds=news_config.latest_feeds,
                topic_feeds=news_config.topic_feeds,
                default_max_results=news_config.default_max_results,
                timeout_seconds=news_config.timeout_seconds,
                max_attempts=news_config.max_attempts,
                backoff_seconds=news_config.backoff_seconds,
                logger=logger,
            )

        self._latest_driver = _build(NewsMode.LATEST)
        self._search_driver = _build(NewsMode.SEARCH)
        self._topic_driver = _build(NewsMode.TOPIC)

    def start(self) -> None:
        """
        Start the module.

        Registers `news.latest`, `news.search`, and `news.topic` and
        their Tools - unless disabled via `[news].enabled = false`
        configuration.
        """

        if not self._enabled:
            self._logger.info(
                "News module is disabled by configuration; not "
                "registering its Capabilities or Tools."
            )
            return

        self._capability_registry.register(
            CapabilityDefinition(
                id=NEWS_CAPABILITY_LATEST,
                name="News Latest",
                description=(
                    "Returns the latest headlines from PARIKA's "
                    "configured general news feeds."
                ),
                category=CapabilityCategory.TOOL,
                tags=frozenset({"news", "network"}),
                metadata={"tool_affordance": NEWS_TOOL_AFFORDANCES[NEWS_CAPABILITY_LATEST]},  # type: ignore[arg-type]
            )
        )
        self._capability_registry.register(
            CapabilityDefinition(
                id=NEWS_CAPABILITY_SEARCH,
                name="News Search",
                description=(
                    "Searches recent news coverage for a free-text "
                    "query."
                ),
                category=CapabilityCategory.TOOL,
                tags=frozenset({"news", "network"}),
                metadata={"tool_affordance": NEWS_TOOL_AFFORDANCES[NEWS_CAPABILITY_SEARCH]},  # type: ignore[arg-type]
            )
        )
        self._capability_registry.register(
            CapabilityDefinition(
                id=NEWS_CAPABILITY_TOPIC,
                name="News Topic",
                description=(
                    "Returns the latest headlines for a specific "
                    "topic."
                ),
                category=CapabilityCategory.TOOL,
                tags=frozenset({"news", "network"}),
                metadata={"tool_affordance": NEWS_TOOL_AFFORDANCES[NEWS_CAPABILITY_TOPIC]},  # type: ignore[arg-type]
            )
        )

        self._tool_manager.register(create_news_latest_tool(), self._latest_driver)
        self._tool_manager.register(create_news_search_tool(), self._search_driver)
        self._tool_manager.register(create_news_topic_tool(), self._topic_driver)

        # Register native implementations
        if self._implementation_registry is not None:
            for cap_id, tool_id, name in [
                (NEWS_CAPABILITY_LATEST, NEWS_TOOL_ID_LATEST, "News Latest"),
                (NEWS_CAPABILITY_SEARCH, NEWS_TOOL_ID_SEARCH, "News Search"),
                (NEWS_CAPABILITY_TOPIC, NEWS_TOOL_ID_TOPIC, "News Topic"),
            ]:
                impl = self._implementation_registry.register_implementation(
                    capability_id=cap_id,
                    source=ImplementationSource.PARIKA_NATIVE,
                    name=f"Native {name}",
                    description=f"Native PARIKA implementation of {cap_id}",
                    version="1.0.0",
                    metadata=ImplementationMetadata(
                        runtime_type="native",
                        tool_ids=(tool_id,),
                        tags=("native", "tool", "news"),
                    ),
                )
                self._implementation_registry.update_implementation_status(
                    impl.id, ImplementationStatus.ACTIVE
                )

        if self._health_manager is not None:
            self._health_manager.register(
                MODULE_HEALTH_COMPONENT_ID,
                check=self._check_health,
            )

        self._logger.info("News module started.")

    def stop(self) -> None:
        """
        Stop the module.

        Unregisters every News Tool, Capability, and native
        implementation. A no-op when the module was disabled by
        configuration.
        """

        if not self._enabled:
            return

        if self._health_manager is not None:
            self._health_manager.unregister(MODULE_HEALTH_COMPONENT_ID)

        self._tool_manager.unregister(NEWS_TOOL_ID_LATEST)
        self._tool_manager.unregister(NEWS_TOOL_ID_SEARCH)
        self._tool_manager.unregister(NEWS_TOOL_ID_TOPIC)
        self._capability_registry.unregister(NEWS_CAPABILITY_LATEST)
        self._capability_registry.unregister(NEWS_CAPABILITY_SEARCH)
        self._capability_registry.unregister(NEWS_CAPABILITY_TOPIC)

        # Unregister native implementations
        if self._implementation_registry is not None:
            for cap_id in [NEWS_CAPABILITY_LATEST, NEWS_CAPABILITY_SEARCH, NEWS_CAPABILITY_TOPIC]:
                impls = self._implementation_registry.get_implementations_for_capability(
                    cap_id,
                    source=ImplementationSource.PARIKA_NATIVE,
                )
                for impl in impls:
                    self._implementation_registry.unregister_implementation(impl.id)

        self._logger.info("News module stopped.")

    def _check_health(self) -> HealthCheckResult:
        """
        Report the operational health of the News Module.

        The module is considered healthy whenever it is active; it
        holds no persistent connection to monitor.
        """

        return HealthCheckResult(status=HealthStatus.HEALTHY)
