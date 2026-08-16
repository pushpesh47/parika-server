"""
PARIKA Expense Module - Driver

Implements the ModuleDriver contract for the Expense Management
Module.

ExpenseModuleDriver owns only the module's *registration* lifecycle:
starting registers the seven `expense.*` Capabilities with
CapabilityRegistry and their seven Tools with ToolManager (one Tool
per Capability - see `parika/tools/expense/manifest.py`'s module
docstring); stopping unregisters all fourteen. When a HealthManager is
supplied, the module also registers a health check for itself.

The shared `ExpenseService` (and the `ExpenseStorage`/SQLite
connection it owns) is constructed once at the composition root
(`parika/interfaces/runtime.py`), exactly like `TtsOperationRegistry`/
`VoiceLanguagePreferenceStore` are for the Voice Module - never by
this driver itself - so the exact same instance is also reachable
through `ServiceContainer` by the direct Expense API endpoints (see
`parika/tools/expense/service.py`'s own module docstring for why this
matters: one shared data path, not two).

ExpenseModuleDriver never bypasses the architecture: it interacts
with CapabilityRegistry and ToolManager exclusively through their
public APIs and never executes capabilities or tools directly itself.
"""

from __future__ import annotations

from parika.core.capability_registry.capability_category import CapabilityCategory
from parika.core.capability_registry.capability_definition import CapabilityDefinition
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.health_manager.health_check_result import HealthCheckResult
from parika.core.health_manager.health_manager import HealthManager
from parika.core.health_manager.health_status import HealthStatus
from parika.core.logger.logger import Logger
from parika.core.module_manager.driver import ModuleDriver
from parika.core.tool_manager.tool_manager import ToolManager
from parika.tools.expense.driver import ExpenseToolDriver
from parika.tools.expense.manifest import (
    EXPENSE_TOOL_AFFORDANCES,
    OPERATION_CAPABILITY_ID,
    OPERATION_TOOL_ID,
    ExpenseOperation,
    create_expense_tool,
)
from parika.tools.expense.service import ExpenseService

MODULE_HEALTH_COMPONENT_ID = "module.expense"

_CAPABILITY_NAMES: dict[ExpenseOperation, str] = {
    ExpenseOperation.ADD: "Expense Add",
    ExpenseOperation.GET: "Expense Get",
    ExpenseOperation.LIST: "Expense List",
    ExpenseOperation.UPDATE: "Expense Update",
    ExpenseOperation.REMOVE: "Expense Remove",
    ExpenseOperation.SUMMARIZE: "Expense Summarize",
    ExpenseOperation.COMPARE: "Expense Compare Periods",
}


class ExpenseModuleDriver(ModuleDriver):
    """
    Runtime driver for the Expense Management Module.
    """

    def __init__(
        self,
        *,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        service: ExpenseService,
        logger: Logger,
        health_manager: HealthManager | None = None,
    ) -> None:
        """
        Initialize the ExpenseModuleDriver.

        Args:
            capability_registry:
                Registry used to register/unregister every
                `expense.*` Capability.

            tool_manager:
                Manager used to register/unregister every Expense
                Tool.

            service:
                The already-constructed, shared `ExpenseService` (see
                this module's own docstring for why it is constructed
                at the composition root rather than here).

            logger:
                PARIKA Logger component.

            health_manager:
                Optional HealthManager.
        """

        self._capability_registry = capability_registry
        self._tool_manager = tool_manager
        self._service = service
        self._health_manager = health_manager
        self._logger = logger.get_logger(__name__)
        self._enabled = service.config.enabled

        self._drivers: dict[ExpenseOperation, ExpenseToolDriver] = {
            operation: ExpenseToolDriver(operation, service=service)
            for operation in ExpenseOperation
        }

    def start(self) -> None:
        """
        Start the module.

        Registers every `expense.*` Capability and its Tool - unless
        disabled via `[expense].enabled = false` configuration.
        """

        if not self._enabled:
            self._logger.info(
                "Expense module is disabled by configuration; not "
                "registering its Capabilities or Tools."
            )
            return

        for operation in ExpenseOperation:
            capability_id = OPERATION_CAPABILITY_ID[operation]

            self._capability_registry.register(
                CapabilityDefinition(
                    id=capability_id,
                    name=_CAPABILITY_NAMES[operation],
                    description=EXPENSE_TOOL_AFFORDANCES[capability_id]["description"],
                    category=CapabilityCategory.TOOL,
                    tags=frozenset({"expense", "finance", "personal"}),
                    metadata={  # type: ignore[arg-type]
                        "tool_affordance": EXPENSE_TOOL_AFFORDANCES[capability_id]
                    },
                )
            )
            self._tool_manager.register(
                create_expense_tool(operation), self._drivers[operation]
            )

        if self._health_manager is not None:
            self._health_manager.register(
                MODULE_HEALTH_COMPONENT_ID, check=self._check_health
            )

        self._logger.info("Expense module started.")

    def stop(self) -> None:
        """
        Stop the module.

        Unregisters every Expense Tool and Capability. A no-op when
        the module was disabled by configuration.
        """

        if not self._enabled:
            return

        if self._health_manager is not None:
            self._health_manager.unregister(MODULE_HEALTH_COMPONENT_ID)

        for operation in ExpenseOperation:
            self._tool_manager.unregister(OPERATION_TOOL_ID[operation])
            self._capability_registry.unregister(OPERATION_CAPABILITY_ID[operation])

        self._logger.info("Expense module stopped.")

    def _check_health(self) -> HealthCheckResult:
        """
        Report the operational health of the Expense Module.

        The module is considered healthy whenever it is active; its
        storage failures surface per-request as
        `ExpensePersistenceError`, not as a degraded background
        connection to monitor here.
        """

        return HealthCheckResult(status=HealthStatus.HEALTHY)
