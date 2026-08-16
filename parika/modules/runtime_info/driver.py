"""
PARIKA Runtime Info Module - Driver

Implements the ModuleDriver contract for the Runtime Info Module.

RuntimeInfoModuleDriver owns the module's runtime lifecycle: starting
registers the `runtime.current_datetime` Capability with
CapabilityRegistry and the Runtime Info Tool with ToolManager; stopping
unregisters both. When a HealthManager is supplied, the module also
registers a health check for itself.

RuntimeInfoModuleDriver never bypasses the architecture: it interacts
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
from parika.core.health_manager.health_check_result import (
    HealthCheckResult,
)
from parika.core.health_manager.health_manager import HealthManager
from parika.core.health_manager.health_status import HealthStatus
from parika.core.logger.logger import Logger
from parika.core.module_manager.driver import ModuleDriver
from parika.core.tool_manager.tool_manager import ToolManager
from parika.tools.runtime_info.driver import RuntimeInfoToolDriver
from parika.tools.runtime_info.manifest import (
    RUNTIME_INFO_CAPABILITY_ID,
    RUNTIME_INFO_TOOL_ID,
    RUNTIME_INFO_TOOL_AFFORDANCE,
    create_runtime_info_tool,
)

MODULE_HEALTH_COMPONENT_ID = "module.runtime_info"


class RuntimeInfoModuleDriver(ModuleDriver):
    """
    Runtime driver for the Runtime Info Module.

    On start(), registers the `runtime.current_datetime` Capability
    and its supporting Tool. On stop(), unregisters both. Registration
    and execution are delegated entirely to CapabilityRegistry,
    ToolManager, and RuntimeInfoToolDriver; this driver only
    coordinates the module's own lifecycle.
    """

    def __init__(
        self,
        *,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger: Logger,
        health_manager: HealthManager | None = None,
    ) -> None:
        """
        Initialize the RuntimeInfoModuleDriver.

        Args:
            capability_registry:
                Registry used to register/unregister the
                `runtime.current_datetime` Capability.

            tool_manager:
                Manager used to register/unregister the Runtime Info
                Tool.

            logger:
                PARIKA Logger component.

            health_manager:
                Optional HealthManager. When supplied, a health check
                for this module is registered on start() and removed
                on stop().
        """

        self._capability_registry = capability_registry
        self._tool_manager = tool_manager
        self._health_manager = health_manager
        self._logger = logger.get_logger(__name__)
        self._tool_driver = RuntimeInfoToolDriver()

    def start(self) -> None:
        """
        Start the module.

        Registers the `runtime.current_datetime` Capability and the
        Runtime Info Tool.
        """

        self._capability_registry.register(
            CapabilityDefinition(
                id=RUNTIME_INFO_CAPABILITY_ID,
                name="Runtime Info",
                description=(
                    "Returns the current date and time, optionally in "
                    "a specific timezone, from the system clock."
                ),
                category=CapabilityCategory.TOOL,
                tags=frozenset({"runtime", "system", "datetime"}),
                metadata={"tool_affordance": RUNTIME_INFO_TOOL_AFFORDANCE},  # type: ignore[arg-type]
            )
        )

        self._tool_manager.register(
            create_runtime_info_tool(),
            self._tool_driver,
        )

        if self._health_manager is not None:
            self._health_manager.register(
                MODULE_HEALTH_COMPONENT_ID,
                check=self._check_health,
            )

        self._logger.info("Runtime Info module started.")

    def stop(self) -> None:
        """
        Stop the module.

        Unregisters the Runtime Info Tool and the
        `runtime.current_datetime` Capability.
        """

        if self._health_manager is not None:
            self._health_manager.unregister(MODULE_HEALTH_COMPONENT_ID)

        self._tool_manager.unregister(RUNTIME_INFO_TOOL_ID)
        self._capability_registry.unregister(RUNTIME_INFO_CAPABILITY_ID)

        self._logger.info("Runtime Info module stopped.")

    def _check_health(self) -> HealthCheckResult:
        """
        Report the operational health of the Runtime Info Module.

        The module is considered healthy whenever it is active; it
        depends only on the local system clock.
        """

        return HealthCheckResult(status=HealthStatus.HEALTHY)
