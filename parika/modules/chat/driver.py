"""
PARIKA Chat Module - Driver

Implements the ModuleDriver contract for the Chat Module.

ChatModuleDriver owns the module's runtime lifecycle: starting
registers the `chat.respond` Capability (category `LLM`) with
CapabilityRegistry; stopping unregisters it. When a HealthManager is
supplied, the module also registers a health check for itself.

Unlike the Web Search Module, this module registers no Tool: a
capability in the `LLM` category is always satisfied by an enabled
Provider exposing a model with `ModelCapability.TEXT_GENERATION`
(see `Planner._select_provider_model` and
`PARIKA_Decision_Flow.md` section 4.4), not by ToolManager.
ChatModuleDriver never bypasses the architecture: it interacts with
CapabilityRegistry exclusively through its public API and never
executes capabilities itself.
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

CHAT_CAPABILITY_ID = "chat.respond"
"""
Identifier of the Capability registered by this module.
"""

MODULE_HEALTH_COMPONENT_ID = "module.chat"


class ChatModuleDriver(ModuleDriver):
    """
    Runtime driver for the Chat Module.

    On start(), registers the `chat.respond` Capability. On stop(),
    unregisters it. Registration is delegated entirely to
    CapabilityRegistry; this driver only coordinates the module's own
    lifecycle.
    """

    def __init__(
        self,
        *,
        capability_registry: CapabilityRegistry,
        logger: Logger,
        health_manager: HealthManager | None = None,
    ) -> None:
        """
        Initialize the ChatModuleDriver.

        Args:
            capability_registry:
                Registry used to register/unregister the
                `chat.respond` Capability.

            logger:
                PARIKA Logger component.

            health_manager:
                Optional HealthManager. When supplied, a health check
                for this module is registered on start() and removed
                on stop().
        """

        self._capability_registry = capability_registry
        self._health_manager = health_manager
        self._logger = logger.get_logger(__name__)

    def start(self) -> None:
        """
        Start the module.

        Registers the `chat.respond` Capability.
        """

        self._capability_registry.register(
            CapabilityDefinition(
                id=CHAT_CAPABILITY_ID,
                name="Chat Respond",
                description=(
                    "Produces a conversational response using an "
                    "enabled LLM Provider."
                ),
                category=CapabilityCategory.LLM,
                tags=frozenset({"chat", "llm"}),
            )
        )

        if self._health_manager is not None:
            self._health_manager.register(
                MODULE_HEALTH_COMPONENT_ID,
                check=self._check_health,
            )

        self._logger.info("Chat module started.")

    def stop(self) -> None:
        """
        Stop the module.

        Unregisters the `chat.respond` Capability.
        """

        if self._health_manager is not None:
            self._health_manager.unregister(MODULE_HEALTH_COMPONENT_ID)

        self._capability_registry.unregister(CHAT_CAPABILITY_ID)

        self._logger.info("Chat module stopped.")

    def _check_health(self) -> HealthCheckResult:
        """
        Report the operational health of the Chat Module.

        The module is considered healthy whenever it is active; it
        holds no persistent connection to monitor. Provider
        reachability is reported separately by ProviderManager /
        HealthManager registrations owned by the Provider itself.
        """

        return HealthCheckResult(status=HealthStatus.HEALTHY)
