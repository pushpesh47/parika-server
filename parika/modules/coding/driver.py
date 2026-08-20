"""
PARIKA Coding Module - Driver

Implements the ModuleDriver contract for the Coding Module.

On start(), registers every `coding.*` Capability (see
`parika.tools.coding.manifest.CODING_OPERATIONS`) with
CapabilityRegistry and its own Coding Tool with ToolManager. On
stop(), unregisters all of them and shuts down the Coding Tool's
`coding_index.sqlite3` storage. Mirrors `FilesystemModuleDriver`
exactly.
"""

from __future__ import annotations

from pathlib import Path

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
from parika.core.event_bus.event_bus import EventBus
from parika.core.health_manager.health_check_result import HealthCheckResult
from parika.core.health_manager.health_manager import HealthManager
from parika.core.health_manager.health_status import HealthStatus
from parika.core.logger.logger import Logger
from parika.core.module_manager.driver import ModuleDriver
from parika.core.tool_manager.tool_manager import ToolManager
from parika.core.utilities.progress import ProgressReporter
from parika.tools.coding.analyzers.registry import (
    LanguageAnalyzerRegistry,
    default_analyzers,
)
from parika.tools.coding.config import load_coding_config
from parika.tools.coding.driver import CodingToolDriver
from parika.tools.coding.manifest import CODING_OPERATIONS, create_coding_tool
from parika.tools.coding.postgresql_storage import PostgreSQLCodingIndexStorage

MODULE_HEALTH_COMPONENT_ID = "module.coding"


class CodingModuleDriver(ModuleDriver):
    """
    Runtime driver for the Coding Module.
    """

    def __init__(
        self,
        *,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger: Logger,
        database_path: Path,
        event_bus: EventBus | None = None,
        health_manager: HealthManager | None = None,
        configuration: Configuration | None = None,
    ) -> None:
        """
        Initialize the CodingModuleDriver.

        Args:
            capability_registry:
                Registry used to register/unregister every `coding.*`
                Capability.

            tool_manager:
                Manager used to register/unregister every Coding Tool
                operation, and, for `FORMAT`/`LINT`, to dispatch to
                the existing Shell Tool's `shell.execute` capability.

            logger:
                PARIKA Logger component.

            database_path:
                Path to `coding_index.sqlite3`.

            event_bus:
                Optional shared `EventBus`, used to construct one
                `ProgressReporter` per operation so each Coding Tool
                capability reports its own real progress (see
                docs/development/Module_Guide.md
                Addendum A/B). Omitting it leaves every operation
                silently not reporting progress.

            health_manager:
                Optional HealthManager.

            configuration:
                Optional Core `Configuration`, used to read the
                `[coding]` section.
        """

        self._capability_registry = capability_registry
        self._tool_manager = tool_manager
        self._health_manager = health_manager
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

        config = load_coding_config(configuration)
        self._enabled = config.enabled

        self._storage = PostgreSQLCodingIndexStorage(database_path)
        self._registry: LanguageAnalyzerRegistry = LanguageAnalyzerRegistry(
            default_analyzers(
                formatters=config.formatters,
                linters=config.linters,
                tree_sitter_enabled=config.tree_sitter_enabled,
            )
        )
        self._max_file_size_bytes = config.max_file_size_bytes

        self._tool_drivers = {
            spec.operation: CodingToolDriver(
                spec.operation,
                storage=self._storage,
                registry=self._registry,
                max_file_size_bytes=self._max_file_size_bytes,
                tool_manager=self._tool_manager,
                progress_reporter=(
                    ProgressReporter(event_bus, spec.capability_id)
                    if event_bus is not None
                    else None
                ),
            )
            for spec in CODING_OPERATIONS
        }

    @property
    def storage(self) -> CodingIndexStorage:
        """
        The Coding Tool's shared `CodingIndexStorage`, reused by the
        `repository_intelligence` Module's `RepositoryKnowledgeEngine`
        (see
        docs/development/Module_Guide.md
        section 6.1) -- a plain library import, not a Module-to-Module
        dependency.
        """

        return self._storage

    @property
    def registry(self) -> LanguageAnalyzerRegistry:
        """
        The Coding Tool's shared `LanguageAnalyzerRegistry`, reused
        the same way as `storage`.
        """

        return self._registry

    @property
    def max_file_size_bytes(self) -> int:
        """
        The resolved `[coding].max_file_size_bytes`, reused by
        `repository_intelligence` so both Modules apply the same
        bound.
        """

        return self._max_file_size_bytes

    def start(self) -> None:
        """
        Start the module.

        Registers every `coding.*` Capability and its Tool -- unless
        disabled via `[coding].enabled = false`, in which case
        nothing is registered and the module remains inert.
        """

        if not self._enabled:
            self._logger.info(
                "Coding module is disabled by configuration; not "
                "registering its Capabilities or Tools."
            )
            return

        self._storage.initialize()

        for spec in CODING_OPERATIONS:
            self._capability_registry.register(
                CapabilityDefinition(
                    id=spec.capability_id,
                    name=spec.name,
                    description=spec.description,
                    category=CapabilityCategory.TOOL,
                    tags=frozenset({"coding", "development"}),
                )
            )

            self._tool_manager.register(
                create_coding_tool(spec),
                self._tool_drivers[spec.operation],
            )

        if self._health_manager is not None:
            self._health_manager.register(
                MODULE_HEALTH_COMPONENT_ID, check=self._check_health
            )

        self._logger.info("Coding module started.")

    def stop(self) -> None:
        """
        Stop the module.

        Unregisters every Coding Tool and `coding.*` Capability, and
        shuts down `coding_index.sqlite3`.
        """

        if not self._enabled:
            return

        if self._health_manager is not None:
            self._health_manager.unregister(MODULE_HEALTH_COMPONENT_ID)

        for spec in CODING_OPERATIONS:
            self._tool_manager.unregister(spec.tool_id)
            self._capability_registry.unregister(spec.capability_id)

        self._storage.shutdown()

        self._logger.info("Coding module stopped.")

    def _check_health(self) -> HealthCheckResult:
        return HealthCheckResult(status=HealthStatus.HEALTHY)
