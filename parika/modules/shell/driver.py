"""
PARIKA Shell Module - Driver

Implements the ModuleDriver contract for the Shell Module.

ShellModuleDriver owns the module's runtime lifecycle: starting
registers every `shell.*` Capability (see
`parika.tools.shell.manifest.SHELL_OPERATIONS`) with
CapabilityRegistry and its own Shell Tool with ToolManager; stopping
unregisters all of them. When a HealthManager is supplied, the module
also registers a health check for itself.

ShellModuleDriver never bypasses the architecture: it interacts with
CapabilityRegistry and ToolManager exclusively through their public
APIs and never executes capabilities or tools directly itself. It also
never implements any permission logic of its own - the shared
`WorkspacePermissionManager` it is constructed with is the sole
authority every `ShellToolDriver` instance asks before running a
command.
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
from parika.core.health_manager.health_check_result import HealthCheckResult
from parika.core.health_manager.health_manager import HealthManager
from parika.core.health_manager.health_status import HealthStatus
from parika.core.logger.logger import Logger
from parika.core.module_manager.driver import ModuleDriver
from parika.core.permission_manager.workspace_permission_manager import (
    WorkspacePermissionManager,
)
from parika.core.tool_manager.tool_manager import ToolManager
from parika.tools.shell.config import load_shell_config
from parika.tools.shell.driver import ShellToolDriver
from parika.tools.shell.manifest import SHELL_OPERATIONS, create_shell_tool
from parika.tools.shell.process_registry import ShellProcessRegistry

MODULE_HEALTH_COMPONENT_ID = "module.shell"


class ShellModuleDriver(ModuleDriver):
    """
    Runtime driver for the Shell Module.

    On start(), registers every `shell.*` Capability and its
    supporting Tool. On stop(), unregisters all of them. Registration
    and execution are delegated entirely to CapabilityRegistry,
    ToolManager, and ShellToolDriver; this driver only coordinates the
    module's own lifecycle.
    """

    def __init__(
        self,
        *,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        permissions: WorkspacePermissionManager,
        logger: Logger,
        health_manager: HealthManager | None = None,
        configuration: Configuration | None = None,
        implementation_registry: ImplementationRegistry | None = None,
    ) -> None:
        """
        Initialize the ShellModuleDriver.

        Args:
            capability_registry:
                Registry used to register/unregister every `shell.*`
                Capability.

            tool_manager:
                Manager used to register/unregister every Shell Tool.

            permissions:
                Shared `WorkspacePermissionManager` every `ShellToolDriver`
                instance asks before running a command. Required, not
                optional - the Shell Tool has no permission logic of
                its own.

            logger:
                PARIKA Logger component.

            health_manager:
                Optional HealthManager. When supplied, a health check
                for this module is registered on start() and removed
                on stop().

            configuration:
                Optional Core `Configuration`, used to read the
                `[shell]`/`[workspace]` sections (see
                `parika.tools.shell.config`). When omitted (`None`),
                `enabled` defaults to `False`, so the module registers
                nothing.

            implementation_registry:
                Optional ImplementationRegistry for registering native
                capability implementations. When supplied, a
                PARIKA_NATIVE implementation is registered for each
                shell capability.
        """

        self._capability_registry = capability_registry
        self._tool_manager = tool_manager
        self._health_manager = health_manager
        self._logger = logger.get_logger(__name__)
        self._implementation_registry = implementation_registry

        shell_config = load_shell_config(configuration)
        self._enabled = shell_config.enabled

        process_registry = ShellProcessRegistry(
            logger=logger,
            output_buffer_max_bytes=shell_config.output_buffer_max_bytes,
            max_background_processes=shell_config.max_background_processes,
            kill_grace_period_seconds=shell_config.kill_grace_period_seconds,
        )

        self._tool_drivers = {
            spec.operation: ShellToolDriver(
                spec.operation,
                permissions=permissions,
                process_registry=process_registry,
                config=shell_config,
            )
            for spec in SHELL_OPERATIONS
        }

    def start(self) -> None:
        """
        Start the module.

        Registers every `shell.*` Capability and its Tool - unless
        disabled via `[shell].enabled = false` (or the legacy
        `[security].allow_shell_commands = false`) configuration, in
        which case nothing is registered and the module remains inert,
        mirroring `FilesystemModuleDriver.start()`.
        """

        if not self._enabled:
            self._logger.info(
                "Shell module is disabled by configuration; not "
                "registering its Capabilities or Tools."
            )
            return

        for spec in SHELL_OPERATIONS:
            self._capability_registry.register(
                CapabilityDefinition(
                    id=spec.capability_id,
                    name=spec.name,
                    description=spec.description,
                    category=CapabilityCategory.TOOL,
                    tags=frozenset({"shell", "system"}),
                )
            )

            self._tool_manager.register(
                create_shell_tool(spec),
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
                        tags=("native", "tool", "shell"),
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

        self._logger.info("Shell module started.")

    def stop(self) -> None:
        """
        Stop the module.

        Unregisters every Shell Tool, `shell.*` Capability, and native
        implementation. A no-op when the module was disabled by
        configuration, since start() never registered anything.
        """

        if not self._enabled:
            return

        if self._health_manager is not None:
            self._health_manager.unregister(MODULE_HEALTH_COMPONENT_ID)

        for spec in SHELL_OPERATIONS:
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

        self._logger.info("Shell module stopped.")

    def _check_health(self) -> HealthCheckResult:
        """
        Report the operational health of the Shell Module.

        The module is considered healthy whenever it is active; it
        depends only on the local operating system's ability to spawn
        processes.
        """

        return HealthCheckResult(status=HealthStatus.HEALTHY)
