"""
PARIKA Memory Module - Driver

Implements the ModuleDriver contract for the Memory Module.

MemoryModuleDriver owns the module's runtime lifecycle: starting
registers the `memory.remember`, `memory.search`, and `memory.forget`
Capabilities with CapabilityRegistry and their supporting Tools with
ToolManager; stopping unregisters all six. Unlike most Tool Modules,
this one is constructed with a `MemoryManager` dependency (the same
pattern the Knowledge Indexing Module already uses for
`KnowledgeManager`) -- it never bypasses MemoryManager's public API.
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
from typing import TYPE_CHECKING

from parika.core.health_manager.health_check_result import HealthCheckResult
from parika.core.health_manager.health_manager import HealthManager
from parika.core.health_manager.health_status import HealthStatus
from parika.core.logger.logger import Logger
from parika.core.memory_manager.memory_manager import MemoryManager
from parika.core.module_manager.driver import ModuleDriver
from parika.core.tool_manager.tool_manager import ToolManager
from parika.tools.memory.driver import MemoryToolDriver, MemoryToolOperation
from parika.tools.memory.intent import has_explicit_memory_intent
from parika.tools.memory.manifest import (
    MEMORY_CAPABILITY_FORGET,
    MEMORY_CAPABILITY_REMEMBER,
    MEMORY_CAPABILITY_SEARCH,
    MEMORY_TOOL_ID_FORGET,
    MEMORY_TOOL_ID_REMEMBER,
    MEMORY_TOOL_ID_SEARCH,
    MEMORY_TOOL_AFFORDANCES,
    create_memory_forget_tool,
    create_memory_remember_tool,
    create_memory_search_tool,
)

if TYPE_CHECKING:
    from parika.core.configuration.configuration import Configuration

MODULE_HEALTH_COMPONENT_ID = "module.memory"


class MemoryModuleDriver(ModuleDriver):
    """Runtime driver for the Memory Module."""

    def __init__(
        self,
        *,
        memory_manager: MemoryManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger: Logger,
        health_manager: HealthManager | None = None,
        configuration: "Configuration | None" = None,
    ) -> None:
        """
        Parameters
        ----------
        configuration:
            Optional Configuration forwarded to the `memory.remember`
            `MemoryToolDriver` so it can protect Assistant Identity
            (see `parika.tools.memory.identity_guard`). Existing call
            sites that omit this argument are unaffected.
        """

        self._capability_registry = capability_registry
        self._tool_manager = tool_manager
        self._health_manager = health_manager
        self._logger = logger.get_logger(__name__)

        self._remember_driver = MemoryToolDriver(
            MemoryToolOperation.REMEMBER,
            memory_manager=memory_manager,
            configuration=configuration,
        )
        self._search_driver = MemoryToolDriver(
            MemoryToolOperation.SEARCH, memory_manager=memory_manager
        )
        self._forget_driver = MemoryToolDriver(
            MemoryToolOperation.FORGET, memory_manager=memory_manager
        )

    def start(self) -> None:
        """Start the module: register all three Capabilities and Tools."""

        self._capability_registry.register(
            CapabilityDefinition(
                id=MEMORY_CAPABILITY_REMEMBER,
                name="Memory Remember",
                description=(
                    "Permanently remembers a fact or preference about "
                    "the user, retrievable in any future conversation."
                ),
                category=CapabilityCategory.TOOL,
                tags=frozenset({"memory"}),
                metadata={  # type: ignore[arg-type]
                    "tool_affordance": MEMORY_TOOL_AFFORDANCES[MEMORY_CAPABILITY_REMEMBER],
                    "identity_sensitive": True,
                    # Explicit-intent authorization is capability-specific
                    # (meaningful only for memory.remember), so it is
                    # owned entirely by this Tool and handed to AI
                    # Context Engineering as an opaque predicate -- see
                    # `parika.tools.memory.intent`'s module docstring.
                    "authorization_predicate": has_explicit_memory_intent,
                },
            )
        )
        self._capability_registry.register(
            CapabilityDefinition(
                id=MEMORY_CAPABILITY_SEARCH,
                name="Memory Search",
                description="Searches permanently remembered facts and preferences.",
                category=CapabilityCategory.TOOL,
                tags=frozenset({"memory"}),
                metadata={  # type: ignore[arg-type]
                    "tool_affordance": MEMORY_TOOL_AFFORDANCES[MEMORY_CAPABILITY_SEARCH],
                    "identity_sensitive": True,
                },
            )
        )
        self._capability_registry.register(
            CapabilityDefinition(
                id=MEMORY_CAPABILITY_FORGET,
                name="Memory Forget",
                description="Permanently forgets a remembered fact or preference.",
                category=CapabilityCategory.TOOL,
                tags=frozenset({"memory"}),
                metadata={  # type: ignore[arg-type]
                    "tool_affordance": MEMORY_TOOL_AFFORDANCES[MEMORY_CAPABILITY_FORGET],
                    "identity_sensitive": True,
                },
            )
        )

        self._tool_manager.register(create_memory_remember_tool(), self._remember_driver)
        self._tool_manager.register(create_memory_search_tool(), self._search_driver)
        self._tool_manager.register(create_memory_forget_tool(), self._forget_driver)

        if self._health_manager is not None:
            self._health_manager.register(
                MODULE_HEALTH_COMPONENT_ID, check=self._check_health
            )

        self._logger.info("Memory module started.")

    def stop(self) -> None:
        """Stop the module: unregister all three Tools and Capabilities."""

        if self._health_manager is not None:
            self._health_manager.unregister(MODULE_HEALTH_COMPONENT_ID)

        self._tool_manager.unregister(MEMORY_TOOL_ID_REMEMBER)
        self._tool_manager.unregister(MEMORY_TOOL_ID_SEARCH)
        self._tool_manager.unregister(MEMORY_TOOL_ID_FORGET)
        self._capability_registry.unregister(MEMORY_CAPABILITY_REMEMBER)
        self._capability_registry.unregister(MEMORY_CAPABILITY_SEARCH)
        self._capability_registry.unregister(MEMORY_CAPABILITY_FORGET)

        self._logger.info("Memory module stopped.")

    def _check_health(self) -> HealthCheckResult:
        return HealthCheckResult(status=HealthStatus.HEALTHY)
