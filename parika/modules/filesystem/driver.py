"""
PARIKA Filesystem Module - Driver

Implements the ModuleDriver contract for the Filesystem Module.

FilesystemModuleDriver owns the module's runtime lifecycle: starting
registers every `filesystem.*` Capability (see
`parika.tools.filesystem.manifest.FILESYSTEM_OPERATIONS`) with
CapabilityRegistry and its own Filesystem Tool with ToolManager;
stopping unregisters all of them. When a HealthManager is supplied,
the module also registers a health check for itself.

FilesystemModuleDriver never bypasses the architecture: it interacts
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
from parika.core.permission_manager.workspace_permission_manager import (
    WorkspacePermissionManager,
)
from parika.core.tool_manager.tool_manager import ToolManager
from parika.tools.filesystem.config import load_filesystem_config
from parika.tools.filesystem.driver import FilesystemToolDriver
from parika.tools.filesystem.manifest import (
    FILESYSTEM_OPERATIONS,
    create_filesystem_tool,
)
from parika.tools.filesystem.security import PathSecurity, PathSecurityConfig

MODULE_HEALTH_COMPONENT_ID = "module.filesystem"


class FilesystemModuleDriver(ModuleDriver):
    """
    Runtime driver for the Filesystem Module.

    On start(), registers every `filesystem.*` Capability and its
    supporting Tool. On stop(), unregisters all of them. Registration
    and execution are delegated entirely to CapabilityRegistry,
    ToolManager, and FilesystemToolDriver; this driver only
    coordinates the module's own lifecycle.
    """

    def __init__(
        self,
        *,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger: Logger,
        health_manager: HealthManager | None = None,
        configuration: Configuration | None = None,
        permissions: WorkspacePermissionManager | None = None,
        implementation_registry: ImplementationRegistry | None = None,
    ) -> None:
        """
        Initialize the FilesystemModuleDriver.

        Args:
            capability_registry:
                Registry used to register/unregister every
                `filesystem.*` Capability.

            tool_manager:
                Manager used to register/unregister every Filesystem
                Tool.

            logger:
                PARIKA Logger component.

            health_manager:
                Optional HealthManager. When supplied, a health check
                for this module is registered on start() and removed
                on stop().

            configuration:
                Optional Core `Configuration`, used to read the
                `[filesystem]`/`[workspace]` sections (see
                `parika.tools.filesystem.config`). When omitted
                (`None`), `allowed_roots` defaults to empty, so the
                module registers every Capability but every mutating/
                destructive operation rejects every path - deny-by-
                default rather than silently permissive. Reads are
                unaffected either way.

            permissions:
                Optional shared `WorkspacePermissionManager`. When
                supplied, it becomes the sole authority for every
                mutating/destructive path outside `allowed_roots` -
                see `parika.tools.filesystem.security.PathSecurity`.
                When omitted (`None`), such paths are always denied,
                preserving this module's original, self-contained
                behavior.

            implementation_registry:
                Optional ImplementationRegistry for registering native
                capability implementations. When supplied, a
                PARIKA_NATIVE implementation is registered for each
                filesystem capability.
        """

        self._capability_registry = capability_registry
        self._tool_manager = tool_manager
        self._health_manager = health_manager
        self._logger = logger.get_logger(__name__)
        self._implementation_registry = implementation_registry

        filesystem_config = load_filesystem_config(configuration)
        self._enabled = filesystem_config.enabled

        security = PathSecurity(
            PathSecurityConfig(
                allowed_roots=filesystem_config.allowed_roots,
                allow_write=filesystem_config.allow_write,
                allow_delete=filesystem_config.allow_delete,
            ),
            permissions=permissions,
        )

        self._tool_drivers = {
            spec.operation: FilesystemToolDriver(
                spec.operation,
                security=security,
                default_search_recursive=filesystem_config.default_search_recursive,
                max_walk_entries=filesystem_config.max_walk_entries,
                watch_poll_interval_seconds=(
                    filesystem_config.watch_poll_interval_seconds
                ),
                watch_max_duration_seconds=(
                    filesystem_config.watch_max_duration_seconds
                ),
            )
            for spec in FILESYSTEM_OPERATIONS
        }

    def start(self) -> None:
        """
        Start the module.

        Registers every `filesystem.*` Capability and its Tool -
        unless disabled via `[filesystem].enabled = false`
        configuration, in which case nothing is registered and the
        module remains inert, mirroring
        `WebSearchModuleDriver.start()`.
        """

        if not self._enabled:
            self._logger.info(
                "Filesystem module is disabled by configuration; "
                "not registering its Capabilities or Tools."
            )
            return

        for spec in FILESYSTEM_OPERATIONS:
            # filesystem.write is terminal - it completes the requested side effect
            # (creating/updating a file). Other filesystem operations return data
            # requiring synthesis.
            is_terminal = spec.capability_id == "filesystem.write"

            self._capability_registry.register(
                CapabilityDefinition(
                    id=spec.capability_id,
                    name=spec.name,
                    description=spec.description,
                    category=CapabilityCategory.TOOL,
                    tags=frozenset({"filesystem", "system"}),
                    metadata={  # type: ignore[arg-type]
                        "tool_affordance": {
                            "purpose": spec.purpose,
                            "use_when": spec.use_when,
                            "avoid_when": spec.avoid_when,
                            "requires": spec.requires,
                            "result_semantics": spec.result_semantics,
                            "failure_semantics": spec.failure_semantics,
                            "parameters": spec.parameters,
                        },
                        "decomposition_terminal": is_terminal,
                    },
                )
            )

            self._tool_manager.register(
                create_filesystem_tool(spec),
                self._tool_drivers[spec.operation],
            )

            # Register native implementation for this capability
            if self._implementation_registry is not None:
                impl = self._implementation_registry.register_implementation(
                    capability_id=spec.capability_id,
                    source=ImplementationSource.PARIKA_NATIVE,
                    name=f"Native {spec.name}",
                    description=f"Native PARIKA implementation of {spec.capability_id}",
                    version="1.0.0",
                    metadata=ImplementationMetadata(
                        runtime_type="native",
                        tool_ids=(spec.tool_id,),
                        tags=("native", "tool", "filesystem"),
                    ),
                )
                # Activate the implementation
                self._implementation_registry.update_implementation_status(
                    impl.id, ImplementationStatus.ACTIVE
                )

        if self._health_manager is not None:
            self._health_manager.register(
                MODULE_HEALTH_COMPONENT_ID,
                check=self._check_health,
            )

        self._logger.info("Filesystem module started.")

    def stop(self) -> None:
        """
        Stop the module.

        Unregisters every Filesystem Tool, `filesystem.*`
        Capability, and native implementation. A no-op when the module was
        disabled by configuration, since `start()` never registered anything.
        """

        if not self._enabled:
            return

        if self._health_manager is not None:
            self._health_manager.unregister(MODULE_HEALTH_COMPONENT_ID)

        for spec in FILESYSTEM_OPERATIONS:
            self._tool_manager.unregister(spec.tool_id)
            self._capability_registry.unregister(spec.capability_id)
            # Unregister native implementation
            if self._implementation_registry is not None:
                impls = self._implementation_registry.get_implementations_for_capability(
                    spec.capability_id,
                    source=ImplementationSource.PARIKA_NATIVE,
                )
                for impl in impls:
                    self._implementation_registry.unregister_implementation(impl.id)

        self._logger.info("Filesystem module stopped.")

    def _check_health(self) -> HealthCheckResult:
        """
        Report the operational health of the Filesystem Module.

        The module is considered healthy whenever it is active; it
        depends only on the local filesystem.
        """

        return HealthCheckResult(status=HealthStatus.HEALTHY)
