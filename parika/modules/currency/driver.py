"""
PARIKA Currency Module - Driver

Implements the ModuleDriver contract for the Currency Module.

CurrencyModuleDriver owns the module's runtime lifecycle: starting
registers the `currency.exchange_rate` and `currency.convert`
Capabilities with CapabilityRegistry and their supporting Tools with
ToolManager; stopping unregisters all four. When a HealthManager is
supplied, the module also registers a health check for itself.

CurrencyModuleDriver never bypasses the architecture: it interacts
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
from parika.tools.currency.config import load_currency_config
from parika.tools.currency.driver import CurrencyToolDriver
from parika.tools.currency.manifest import (
    CURRENCY_CAPABILITY_CONVERT,
    CURRENCY_CAPABILITY_EXCHANGE_RATE,
    CURRENCY_TOOL_ID_CONVERT,
    CURRENCY_TOOL_ID_EXCHANGE_RATE,
    CURRENCY_TOOL_AFFORDANCES,
    CurrencyMode,
    create_currency_convert_tool,
    create_currency_exchange_rate_tool,
)
from parika.tools.currency.protocol import RateBackend
from parika.tools.currency.provider_registry import (
    BackendTuning,
    build_rate_backend,
)
from parika.tools.currency.transport import HttpTransport, UrllibHttpTransport

MODULE_HEALTH_COMPONENT_ID = "module.currency"


class CurrencyModuleDriver(ModuleDriver):
    """
    Runtime driver for the Currency Module.
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
        rate_backend: RateBackend | None = None,
    ) -> None:
        """
        Initialize the CurrencyModuleDriver.

        Args:
            capability_registry:
                Registry used to register/unregister
                `currency.exchange_rate` and `currency.convert`.

            tool_manager:
                Manager used to register/unregister the Currency
                Tools.

            logger:
                PARIKA Logger component.

            health_manager:
                Optional HealthManager.

            configuration:
                Optional Core `Configuration`, used to read the
                `[currency]` section and build a `FailoverRateBackend`
                across every configured provider. Ignored when
                `rate_backend` is supplied explicitly.

            transport:
                Optional HttpTransport override. Defaults to
                `UrllibHttpTransport`. Ignored when `rate_backend` is
                supplied explicitly.

            rate_backend:
                Optional RateBackend override, primarily for tests.
                When supplied, it is used exactly as given and
                `configuration`'s `[currency]` provider selection is
                not consulted at all.
        """

        self._capability_registry = capability_registry
        self._tool_manager = tool_manager
        self._health_manager = health_manager
        self._logger = logger.get_logger(__name__)

        currency_config = load_currency_config(configuration)
        self._enabled = currency_config.enabled

        resolved_transport = transport or UrllibHttpTransport()

        resolved_rate_backend = rate_backend or build_rate_backend(
            currency_config,
            resolved_transport,
            tuning=BackendTuning(
                timeout_seconds=currency_config.timeout_seconds,
                max_attempts=currency_config.max_attempts,
                backoff_seconds=currency_config.backoff_seconds,
            ),
            logger=logger,
        )

        self._exchange_rate_driver = CurrencyToolDriver(
            CurrencyMode.EXCHANGE_RATE,
            rate_backend=resolved_rate_backend,
        )
        self._convert_driver = CurrencyToolDriver(
            CurrencyMode.CONVERT,
            rate_backend=resolved_rate_backend,
        )

    def start(self) -> None:
        """
        Start the module.

        Registers `currency.exchange_rate` and `currency.convert`
        and their Tools - unless disabled via
        `[currency].enabled = false` configuration.
        """

        if not self._enabled:
            self._logger.info(
                "Currency module is disabled by configuration; not "
                "registering its Capabilities or Tools."
            )
            return

        self._capability_registry.register(
            CapabilityDefinition(
                id=CURRENCY_CAPABILITY_EXCHANGE_RATE,
                name="Currency Exchange Rate",
                description=(
                    "Returns the current exchange rate between two "
                    "currencies."
                ),
                category=CapabilityCategory.TOOL,
                tags=frozenset({"currency", "network"}),
                metadata={  # type: ignore[arg-type]
                    "tool_affordance": CURRENCY_TOOL_AFFORDANCES[
                        CURRENCY_CAPABILITY_EXCHANGE_RATE
                    ]
                },
            )
        )
        self._capability_registry.register(
            CapabilityDefinition(
                id=CURRENCY_CAPABILITY_CONVERT,
                name="Currency Convert",
                description=(
                    "Converts an amount from one currency to "
                    "another using the current exchange rate."
                ),
                category=CapabilityCategory.TOOL,
                tags=frozenset({"currency", "network"}),
                metadata={  # type: ignore[arg-type]
                    "tool_affordance": CURRENCY_TOOL_AFFORDANCES[CURRENCY_CAPABILITY_CONVERT]
                },
            )
        )

        self._tool_manager.register(
            create_currency_exchange_rate_tool(), self._exchange_rate_driver
        )
        self._tool_manager.register(
            create_currency_convert_tool(), self._convert_driver
        )

        if self._health_manager is not None:
            self._health_manager.register(
                MODULE_HEALTH_COMPONENT_ID,
                check=self._check_health,
            )

        self._logger.info("Currency module started.")

    def stop(self) -> None:
        """
        Stop the module.

        Unregisters both Currency Tools and both Capabilities. A
        no-op when the module was disabled by configuration.
        """

        if not self._enabled:
            return

        if self._health_manager is not None:
            self._health_manager.unregister(MODULE_HEALTH_COMPONENT_ID)

        self._tool_manager.unregister(CURRENCY_TOOL_ID_EXCHANGE_RATE)
        self._tool_manager.unregister(CURRENCY_TOOL_ID_CONVERT)
        self._capability_registry.unregister(CURRENCY_CAPABILITY_EXCHANGE_RATE)
        self._capability_registry.unregister(CURRENCY_CAPABILITY_CONVERT)

        self._logger.info("Currency module stopped.")

    def _check_health(self) -> HealthCheckResult:
        """
        Report the operational health of the Currency Module.

        The module is considered healthy whenever it is active; it
        holds no persistent connection to monitor.
        """

        return HealthCheckResult(status=HealthStatus.HEALTHY)
