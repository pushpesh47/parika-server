"""
PARIKA Web Search Module - Driver

Implements the ModuleDriver contract for the Web Search Module.

WebSearchModuleDriver owns the module's runtime lifecycle: starting
registers the `web.search` Capability with CapabilityRegistry and the
Web Search Tool with ToolManager; stopping unregisters both. When a
HealthManager is supplied, the module also registers a health check
for itself.

WebSearchModuleDriver never bypasses the architecture: it interacts
with CapabilityRegistry and ToolManager exclusively through their
public APIs and never executes capabilities or tools directly itself.
"""

from __future__ import annotations

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
from parika.tools.web_search.cache import SearchResultCache
from parika.tools.web_search.config import load_web_search_config
from parika.tools.web_search.driver import WebSearchToolDriver
from parika.tools.web_search.manifest import (
    WEB_SEARCH_CAPABILITY_ID,
    WEB_SEARCH_TOOL_ID,
    WEB_SEARCH_TOOL_AFFORDANCE,
    create_web_search_tool,
)
from parika.tools.web_search.page_fetcher import PageFetcher
from parika.tools.web_search.protocol import SearchBackend
from parika.tools.web_search.provider_registry import (
    BackendTuning,
    build_search_backend,
)
from parika.tools.web_search.ranking import RankingWeights
from parika.tools.web_search.transport import HttpTransport, UrllibHttpTransport
from parika.tools.web_search.validation import SearchValidationConfig

MODULE_HEALTH_COMPONENT_ID = "module.web_search"

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 0.5


class WebSearchModuleDriver(ModuleDriver):
    """
    Runtime driver for the Web Search Module.

    On start(), registers the `web.search` Capability and its
    supporting Tool. On stop(), unregisters both. Registration and
    execution are delegated entirely to CapabilityRegistry,
    ToolManager, and WebSearchToolDriver; this driver only coordinates
    the module's own lifecycle.
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
        search_backend: SearchBackend | None = None,
        page_fetcher: PageFetcher | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    ) -> None:
        """
        Initialize the WebSearchModuleDriver.

        Args:
            capability_registry:
                Registry used to register/unregister the `web.search`
                Capability.

            tool_manager:
                Manager used to register/unregister the Web Search
                Tool.

            logger:
                PARIKA Logger component.

            health_manager:
                Optional HealthManager. When supplied, a health check
                for this module is registered on start() and removed
                on stop().

            configuration:
                Optional Core `Configuration`, used to read the
                `[web_search]` section (see `config.py`) and build a
                `FailoverSearchBackend` across every configured,
                available provider (see `provider_registry.py`).
                Ignored when `search_backend` is supplied explicitly.
                When omitted (`None`), the module falls back to a
                single `GoogleHtmlSearchBackend` - `config.py`'s
                built-in default provider - so every existing caller
                keeps working, just against the new default provider.

            transport:
                Optional HttpTransport override. Defaults to
                UrllibHttpTransport.

            search_backend:
                Optional SearchBackend override. When supplied, it is
                used exactly as given and `configuration`'s
                `[web_search]` provider selection is not consulted at
                all - this is what keeps every existing caller/test
                that injects its own fake backend fully unaffected.
                Defaults to a config-driven `FailoverSearchBackend`
                (or a single provider's backend, unwrapped, when only
                one is configured/available - see
                `provider_registry.build_search_backend()`).

            page_fetcher:
                Optional PageFetcher override. Defaults to a
                PageFetcher built on `transport`.

            timeout_seconds:
                Default network timeout applied to every default
                search backend and to the page fetcher.

            max_attempts:
                Default maximum retry attempts applied to every
                default search backend and to the page fetcher.

            backoff_seconds:
                Default retry backoff applied to every default search
                backend and to the page fetcher.
        """

        self._capability_registry = capability_registry
        self._tool_manager = tool_manager
        self._health_manager = health_manager
        self._logger = logger.get_logger(__name__)

        web_search_config = load_web_search_config(configuration)
        self._enabled = web_search_config.enabled

        resolved_transport = transport or UrllibHttpTransport()

        resolved_search_backend = search_backend or build_search_backend(
            web_search_config,
            resolved_transport,
            tuning=BackendTuning(
                timeout_seconds=timeout_seconds,
                max_attempts=max_attempts,
                backoff_seconds=backoff_seconds,
            ),
            logger=logger,
        )

        resolved_page_fetcher = page_fetcher or PageFetcher(
            resolved_transport,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            backoff_seconds=backoff_seconds,
        )

        resolved_cache: SearchResultCache | None = None

        if web_search_config.cache_enabled:
            cache_database_path = (
                configuration.get_project_root()
                / configuration.get("data.directory", "data")
                / "search_cache.sqlite3"
                if configuration is not None
                else None
            )
            resolved_cache = SearchResultCache(
                cache_database_path,
                ttl_seconds=web_search_config.cache_ttl_seconds,
                max_entries=web_search_config.cache_max_entries,
            )
            resolved_cache.initialize()

        self._search_result_cache = resolved_cache

        self._tool_driver = WebSearchToolDriver(
            search_backend=resolved_search_backend,
            page_fetcher=resolved_page_fetcher,
            default_max_results=web_search_config.default_max_results,
            candidate_pool_size=web_search_config.candidate_pool_size,
            ranking_enabled=web_search_config.ranking_enabled,
            ranking_weights=RankingWeights(
                title_weight=web_search_config.ranking_title_weight,
                snippet_weight=web_search_config.ranking_snippet_weight,
                position_decay=web_search_config.ranking_position_decay,
            ),
            dedup_enabled=web_search_config.dedup_enabled,
            dedup_title_similarity_threshold=(
                web_search_config.dedup_title_similarity_threshold
            ),
            validation_enabled=web_search_config.validation_enabled,
            validation_config=SearchValidationConfig(
                min_confidence=web_search_config.validation_min_confidence,
                max_retries=web_search_config.validation_max_retries,
                title_weight=web_search_config.validation_title_weight,
                snippet_weight=web_search_config.validation_snippet_weight,
                url_weight=web_search_config.validation_url_weight,
            ),
            cache=resolved_cache,
        )

    def start(self) -> None:
        """
        Start the module.

        Registers the `web.search` Capability and the Web Search
        Tool - unless disabled via `[web_search].enabled = false`
        configuration, in which case neither is registered and the
        module remains inert, mirroring how a disabled Provider is
        never registered (see `interfaces/runtime.py`).
        """

        if not self._enabled:
            self._logger.info(
                "Web Search module is disabled by configuration; "
                "not registering its Capability or Tool."
            )
            return

        self._capability_registry.register(
            CapabilityDefinition(
                id=WEB_SEARCH_CAPABILITY_ID,
                name="Web Search",
                description=(
                    "Searches the web and optionally extracts the "
                    "readable content of each result page."
                ),
                category=CapabilityCategory.TOOL,
                tags=frozenset({"web", "search", "network"}),
                metadata={"tool_affordance": WEB_SEARCH_TOOL_AFFORDANCE},  # type: ignore[arg-type]
            )
        )

        self._tool_manager.register(
            create_web_search_tool(),
            self._tool_driver,
        )

        if self._health_manager is not None:
            self._health_manager.register(
                MODULE_HEALTH_COMPONENT_ID,
                check=self._check_health,
            )

        self._logger.info("Web Search module started.")

    def stop(self) -> None:
        """
        Stop the module.

        Unregisters the Web Search Tool and the `web.search`
        Capability. A no-op when the module was disabled by
        configuration, since `start()` never registered either.
        """

        if not self._enabled:
            return

        if self._health_manager is not None:
            self._health_manager.unregister(MODULE_HEALTH_COMPONENT_ID)

        self._tool_manager.unregister(WEB_SEARCH_TOOL_ID)
        self._capability_registry.unregister(WEB_SEARCH_CAPABILITY_ID)

        if self._search_result_cache is not None:
            self._search_result_cache.shutdown()

        self._logger.info("Web Search module stopped.")

    def _check_health(self) -> HealthCheckResult:
        """
        Report the operational health of the Web Search Module.

        The module is considered healthy whenever it is active; it
        holds no persistent connection to monitor.
        """

        return HealthCheckResult(status=HealthStatus.HEALTHY)
