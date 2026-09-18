"""
PARIKA Weather Module - Driver

Implements the ModuleDriver contract for the Weather Module.

WeatherModuleDriver owns the module's runtime lifecycle: starting
registers the `weather.current` and `weather.forecast` Capabilities
with CapabilityRegistry and their supporting Tools with ToolManager;
stopping unregisters all four. When a HealthManager is supplied, the
module also registers a health check for itself.

WeatherModuleDriver never bypasses the architecture: it interacts
with CapabilityRegistry and ToolManager exclusively through their
public APIs and never executes capabilities or tools directly itself.
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
from parika.tools.weather.config import load_weather_config
from parika.tools.weather.driver import WeatherToolDriver
from parika.tools.weather.manifest import (
    WEATHER_CAPABILITY_CURRENT,
    WEATHER_CAPABILITY_FORECAST,
    WEATHER_TOOL_ID_CURRENT,
    WEATHER_TOOL_ID_FORECAST,
    WEATHER_TOOL_AFFORDANCES,
    WeatherMode,
    create_weather_current_tool,
    create_weather_forecast_tool,
)
from parika.tools.weather.transport import HttpTransport, UrllibHttpTransport

MODULE_HEALTH_COMPONENT_ID = "module.weather"


class WeatherModuleDriver(ModuleDriver):
    """
    Runtime driver for the Weather Module.
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
        Initialize the WeatherModuleDriver.

        Args:
            capability_registry:
                Registry used to register/unregister
                `weather.current` and `weather.forecast`.

            tool_manager:
                Manager used to register/unregister the Weather
                Tools.

            logger:
                PARIKA Logger component.

            health_manager:
                Optional HealthManager. When supplied, a health check
                for this module is registered on start() and removed
                on stop().

            configuration:
                Optional Core `Configuration`, used to read the
                `[weather]` section. When omitted (`None`), every
                value falls back to its built-in default.

            transport:
                Optional HttpTransport override, primarily for tests.
                Defaults to `UrllibHttpTransport`.

            implementation_registry:
                Optional ImplementationRegistry for registering native
                capability implementations. When supplied, a
                PARIKA_NATIVE implementation is registered for each
                weather capability.
        """

        self._capability_registry = capability_registry
        self._tool_manager = tool_manager
        self._health_manager = health_manager
        self._logger = logger.get_logger(__name__)
        self._implementation_registry = implementation_registry

        weather_config = load_weather_config(configuration)
        self._enabled = weather_config.enabled

        resolved_transport = transport or UrllibHttpTransport()

        self._current_driver = WeatherToolDriver(
            WeatherMode.CURRENT,
            transport=resolved_transport,
            units=weather_config.units,
            timeout_seconds=weather_config.timeout_seconds,
            max_attempts=weather_config.max_attempts,
            backoff_seconds=weather_config.backoff_seconds,
            default_forecast_days=weather_config.default_forecast_days,
        )

        self._forecast_driver = WeatherToolDriver(
            WeatherMode.FORECAST,
            transport=resolved_transport,
            units=weather_config.units,
            timeout_seconds=weather_config.timeout_seconds,
            max_attempts=weather_config.max_attempts,
            backoff_seconds=weather_config.backoff_seconds,
            default_forecast_days=weather_config.default_forecast_days,
        )

    def start(self) -> None:
        """
        Start the module.

        Registers `weather.current` and `weather.forecast` and their
        Tools - unless disabled via `[weather].enabled = false`
        configuration, mirroring `WebSearchModuleDriver.start()`.
        """

        if not self._enabled:
            self._logger.info(
                "Weather module is disabled by configuration; not "
                "registering its Capabilities or Tools."
            )
            return

        self._capability_registry.register(
            CapabilityDefinition(
                id=WEATHER_CAPABILITY_CURRENT,
                name="Weather Current",
                description=(
                    "Returns current weather conditions for a "
                    "location."
                ),
                category=CapabilityCategory.TOOL,
                tags=frozenset({"weather", "network"}),
                metadata={  # type: ignore[arg-type]
                    "tool_affordance": WEATHER_TOOL_AFFORDANCES[WEATHER_CAPABILITY_CURRENT]
                },
            )
        )
        self._capability_registry.register(
            CapabilityDefinition(
                id=WEATHER_CAPABILITY_FORECAST,
                name="Weather Forecast",
                description=(
                    "Returns a multi-day daily weather forecast for "
                    "a location."
                ),
                category=CapabilityCategory.TOOL,
                tags=frozenset({"weather", "network"}),
                metadata={  # type: ignore[arg-type]
                    "tool_affordance": WEATHER_TOOL_AFFORDANCES[WEATHER_CAPABILITY_FORECAST]
                },
            )
        )

        self._tool_manager.register(
            create_weather_current_tool(), self._current_driver
        )
        self._tool_manager.register(
            create_weather_forecast_tool(), self._forecast_driver
        )

        # Register native implementations
        if self._implementation_registry is not None:
            for cap_id, tool_id, name in [
                (WEATHER_CAPABILITY_CURRENT, WEATHER_TOOL_ID_CURRENT, "Weather Current"),
                (WEATHER_CAPABILITY_FORECAST, WEATHER_TOOL_ID_FORECAST, "Weather Forecast"),
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
                        tags=("native", "tool", "weather"),
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

        self._logger.info("Weather module started.")

    def stop(self) -> None:
        """
        Stop the module.

        Unregisters both Weather Tools, both Capabilities, and native
        implementations. A no-op when the module was disabled by
        configuration.
        """

        if not self._enabled:
            return

        if self._health_manager is not None:
            self._health_manager.unregister(MODULE_HEALTH_COMPONENT_ID)

        self._tool_manager.unregister(WEATHER_TOOL_ID_CURRENT)
        self._tool_manager.unregister(WEATHER_TOOL_ID_FORECAST)
        self._capability_registry.unregister(WEATHER_CAPABILITY_CURRENT)
        self._capability_registry.unregister(WEATHER_CAPABILITY_FORECAST)

        # Unregister native implementations
        if self._implementation_registry is not None:
            for cap_id in [WEATHER_CAPABILITY_CURRENT, WEATHER_CAPABILITY_FORECAST]:
                impls = self._implementation_registry.get_implementations_for_capability(
                    cap_id,
                    source=ImplementationSource.PARIKA_NATIVE,
                )
                for impl in impls:
                    self._implementation_registry.unregister_implementation(impl.id)

        self._logger.info("Weather module stopped.")

    def _check_health(self) -> HealthCheckResult:
        """
        Report the operational health of the Weather Module.

        The module is considered healthy whenever it is active; it
        holds no persistent connection to monitor.
        """

        return HealthCheckResult(status=HealthStatus.HEALTHY)
