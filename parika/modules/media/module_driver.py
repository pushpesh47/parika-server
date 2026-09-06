"""
PARIKA Media Module - Driver

Implements the ModuleDriver contract for the Media Module.

MediaModuleDriver owns only the module's *registration* lifecycle:
starting registers the thirteen `media.*` Capabilities with
CapabilityRegistry and their thirteen Tools with ToolManager (one
Tool per Capability - see `parika/tools/media/manifest.py`'s module
docstring); stopping unregisters all twenty-six. When a HealthManager
is supplied, the module also registers a health check for itself.

The shared `MediaStateStore`/`MediaConnectionRegistry` (and the
`MediaResolver` built from them plus `Brain`) are constructed once at
the composition root (`parika/interfaces/runtime.py`), exactly like
`TtsOperationRegistry` is for the Voice Module - never by this driver
itself - so the exact same instances are also reachable through
`ServiceContainer` by the Media API/WebSocket layer (see
`parika/tools/media/state_store.py`'s own module docstring for why
this matters: one shared state/transport, never two).

MediaModuleDriver never bypasses the architecture: it interacts with
CapabilityRegistry and ToolManager exclusively through their public
APIs and never executes capabilities or tools directly itself.
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
from parika.tools.media.connection_registry import MediaCommandDispatcher
from parika.tools.media.config import MediaToolConfig
from parika.tools.media.driver import MediaToolDriver
from parika.tools.media.manifest import (
    MEDIA_TOOL_AFFORDANCES,
    OPERATION_CAPABILITY_ID,
    OPERATION_TOOL_ID,
    MediaOperation,
    create_media_tool,
)
from parika.tools.media.resolution import MediaResolver
from parika.tools.media.state_store import MediaStateStore

MODULE_HEALTH_COMPONENT_ID = "module.media"

_CAPABILITY_NAMES: dict[MediaOperation, str] = {
    MediaOperation.PLAY: "Media Play",
    MediaOperation.PAUSE: "Media Pause",
    MediaOperation.RESUME: "Media Resume",
    MediaOperation.STOP: "Media Stop",
    MediaOperation.SKIP: "Media Skip",
    MediaOperation.PREVIOUS: "Media Previous",
    MediaOperation.SEEK: "Media Seek",
    MediaOperation.SET_VOLUME: "Media Set Volume",
    MediaOperation.MUTE: "Media Mute",
    MediaOperation.UNMUTE: "Media Unmute",
    MediaOperation.SHOW: "Media Show",
    MediaOperation.HIDE: "Media Hide",
    MediaOperation.GET_STATE: "Media Get State",
}


class MediaModuleDriver(ModuleDriver):
    """
    Runtime driver for the Media Module.
    """

    def __init__(
        self,
        *,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        state_store: MediaStateStore,
        dispatcher: MediaCommandDispatcher,
        resolver: MediaResolver,
        config: MediaToolConfig,
        logger: Logger,
        health_manager: HealthManager | None = None,
    ) -> None:
        """
        Initialize the MediaModuleDriver.

        Args:
            capability_registry:
                Registry used to register/unregister every `media.*`
                Capability.

            tool_manager:
                Manager used to register/unregister every Media Tool.

            state_store:
                The already-constructed, shared `MediaStateStore` (see
                this module's own docstring for why it is constructed
                at the composition root rather than here).

            dispatcher:
                The already-constructed, shared
                `MediaCommandDispatcher` (in production, a
                `MediaConnectionRegistry`).

            resolver:
                The already-constructed `MediaResolver`.

            config:
                Already-loaded `MediaToolConfig`.

            logger:
                PARIKA Logger component.

            health_manager:
                Optional HealthManager.
        """

        self._capability_registry = capability_registry
        self._tool_manager = tool_manager
        self._health_manager = health_manager
        self._logger = logger.get_logger(__name__)
        self._enabled = config.enabled

        self._drivers: dict[MediaOperation, MediaToolDriver] = {
            operation: MediaToolDriver(
                operation,
                state_store=state_store,
                dispatcher=dispatcher,
                resolver=resolver,
            )
            for operation in MediaOperation
        }

    def start(self) -> None:
        """
        Start the module.

        Registers every `media.*` Capability and its Tool - unless
        disabled via `[media].enabled = false` configuration.
        """

        if not self._enabled:
            self._logger.info(
                "Media module is disabled by configuration; not "
                "registering its Capabilities or Tools."
            )
            return

        for operation in MediaOperation:
            capability_id = OPERATION_CAPABILITY_ID[operation]

            # Media command dispatch capabilities (play, pause, resume, stop, skip,
            # previous, seek, set_volume, mute, unmute, show, hide) are terminal -
            # they complete the requested user-visible action by dispatching to the
            # Web Client. media.get_state is NOT terminal as it returns state info
            # requiring synthesis.
            is_terminal = operation != MediaOperation.GET_STATE

            self._capability_registry.register(
                CapabilityDefinition(
                    id=capability_id,
                    name=_CAPABILITY_NAMES[operation],
                    description=MEDIA_TOOL_AFFORDANCES[capability_id]["description"],
                    category=CapabilityCategory.TOOL,
                    tags=frozenset({"media", "music", "video", "playback"}),
                    metadata={  # type: ignore[arg-type]
                        "tool_affordance": MEDIA_TOOL_AFFORDANCES[capability_id],
                        "decomposition_terminal": is_terminal,
                    },
                )
            )
            self._tool_manager.register(
                create_media_tool(operation), self._drivers[operation]
            )

        if self._health_manager is not None:
            self._health_manager.register(
                MODULE_HEALTH_COMPONENT_ID, check=self._check_health
            )

        self._logger.info("Media module started.")

    def stop(self) -> None:
        """
        Stop the module.

        Unregisters every Media Tool and Capability. A no-op when the
        module was disabled by configuration.
        """

        if not self._enabled:
            return

        if self._health_manager is not None:
            self._health_manager.unregister(MODULE_HEALTH_COMPONENT_ID)

        for operation in MediaOperation:
            self._tool_manager.unregister(OPERATION_TOOL_ID[operation])
            self._capability_registry.unregister(OPERATION_CAPABILITY_ID[operation])

        self._logger.info("Media module stopped.")

    def _check_health(self) -> HealthCheckResult:
        """
        Report the operational health of the Media Module.

        The module is considered healthy whenever it is active;
        whether a Web Client is actually connected is reported through
        `MediaState.client_connected` (`media.get_state`/`GET
        /api/v1/media/state`), not through this health check, since an
        unconnected Web Client is a normal, expected condition (see
        `docs/architecture/adr/0004-media-capability.md`), not a
        degraded PARIKA component.
        """

        return HealthCheckResult(status=HealthStatus.HEALTHY)
