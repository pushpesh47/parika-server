"""
PARIKA Module Manager

Maintains the authoritative runtime registry of Modules.

The ModuleManager is responsible for registering and unregistering
Modules, managing their runtime lifecycle, providing lookup and
enumeration operations, and publishing module lifecycle events.

The ModuleManager does not perform module discovery, package
installation, planning, routing, permission evaluation, or capability
registration.
"""

from __future__ import annotations

from dataclasses import replace
from threading import RLock

from parika.core.configuration import Configuration
from parika.core.event_bus import EventBus
from parika.core.logger import Logger

from .events import (
    ModuleLoadedEvent,
    ModuleRegisteredEvent,
    ModuleStateChangedEvent,
    ModuleUnloadedEvent,
    ModuleUnregisteredEvent,
)
from .exceptions import (
    ModuleAlreadyLoadedError,
    ModuleAlreadyRegisteredError,
    ModuleLoadError,
    ModuleNotFoundError,
    ModuleNotLoadedError,
    ModuleUnloadError,
)
from .module import Module
from .state import ModuleState


MODULE_REGISTERED_EVENT = "module.registered"
MODULE_UNREGISTERED_EVENT = "module.unregistered"
MODULE_LOADED_EVENT = "module.loaded"
MODULE_UNLOADED_EVENT = "module.unloaded"
MODULE_STATE_CHANGED_EVENT = "module.state_changed"


class ModuleManager:
    """
    Maintains the runtime registry of Modules.

    The ModuleManager owns the authoritative registry of all registered
    Modules and coordinates their lifecycle.
    """

    def __init__(
        self,
        configuration: Configuration,
        logger: Logger,
        event_bus: EventBus,
    ) -> None:
        """
        Initialize the ModuleManager.
        """
        self._configuration = configuration
        self._logger = logger.get_logger(__name__)
        self._event_bus = event_bus

        self._modules: dict[str, Module] = {}
        self._lock = RLock()

    def register(self, module: Module) -> None:
        """
        Register a Module.
        """
        with self._lock:
            if module.id in self._modules:
                raise ModuleAlreadyRegisteredError(
                    f"Module '{module.id}' is already registered."
                )

            self._modules[module.id] = module

            self._logger.info(
                "Registered module '%s'.",
                module.id,
            )

            self._event_bus.publish(
                MODULE_REGISTERED_EVENT,
                ModuleRegisteredEvent(module=module)
            )

    def unregister(self, module_id: str) -> None:
        """
        Unregister a Module.
        """
        with self._lock:
            module = self._get_module(module_id)

            self._modules.pop(module_id)

            self._logger.info(
                "Unregistered module '%s'.",
                module.id,
            )

            self._event_bus.publish(
                MODULE_UNREGISTERED_EVENT,
                ModuleUnregisteredEvent(module=module)
            )

    def get(self, module_id: str) -> Module:
        """
        Retrieve a registered Module.
        """
        with self._lock:
            return self._get_module(module_id)

    def contains(self, module_id: str) -> bool:
        """
        Determine whether a Module is registered.
        """
        with self._lock:
            return module_id in self._modules

    def get_all(self) -> tuple[Module, ...]:
        """
        Return all registered Modules.
        """
        with self._lock:
            return tuple(self._modules.values())

    def get_active(self) -> tuple[Module, ...]:
        """
        Return all active Modules.
        """
        with self._lock:
            return tuple(
                module
                for module in self._modules.values()
                if module.state is ModuleState.ACTIVE
            )

    def load(self, module_id: str) -> None:
        """
        Start a registered Module.
        """
        with self._lock:
            module = self._get_module(module_id)

            if module.state is ModuleState.ACTIVE:
                raise ModuleAlreadyLoadedError(
                    f"Module '{module.id}' is already active."
                )

            try:
                module.driver.start()

                updated = replace(
                    module,
                    state=ModuleState.ACTIVE,
                )

                self._modules[module.id] = updated

                self._logger.info(
                    "Loaded module '%s'.",
                    module.id,
                )

                self._event_bus.publish(
                    MODULE_LOADED_EVENT,
                    ModuleLoadedEvent(module=updated)
                )

                self._event_bus.publish(
                    MODULE_STATE_CHANGED_EVENT,
                    ModuleStateChangedEvent(
                        module=updated,
                        previous_state=module.state,
                        current_state=ModuleState.ACTIVE,
                    )
                )

            except Exception as exc:
                failed = replace(
                    module,
                    state=ModuleState.FAILED,
                )

                self._modules[module.id] = failed

                self._logger.exception(
                    "Failed to load module '%s'.",
                    module.id,
                )

                self._event_bus.publish(
                    MODULE_STATE_CHANGED_EVENT,
                    ModuleStateChangedEvent(
                        module=failed,
                        previous_state=module.state,
                        current_state=ModuleState.FAILED,
                    )
                )

                raise ModuleLoadError(
                    f"Failed to load module '{module.id}'."
                ) from exc

    def unload(self, module_id: str) -> None:
        """
        Stop a registered Module.
        """
        with self._lock:
            module = self._get_module(module_id)

            if module.state is not ModuleState.ACTIVE:
                raise ModuleNotLoadedError(
                    f"Module '{module.id}' is not active."
                )

            try:
                module.driver.stop()

                updated = replace(
                    module,
                    state=ModuleState.INACTIVE,
                )

                self._modules[module.id] = updated

                self._logger.info(
                    "Unloaded module '%s'.",
                    module.id,
                )

                self._event_bus.publish(
                    MODULE_UNLOADED_EVENT,
                    ModuleUnloadedEvent(module=updated)
                )

                self._event_bus.publish(
                    MODULE_STATE_CHANGED_EVENT,
                    ModuleStateChangedEvent(
                        module=updated,
                        previous_state=module.state,
                        current_state=ModuleState.INACTIVE,
                    )
                )

            except Exception as exc:
                failed = replace(
                    module,
                    state=ModuleState.FAILED,
                )

                self._modules[module.id] = failed

                self._logger.exception(
                    "Failed to unload module '%s'.",
                    module.id,
                )

                self._event_bus.publish(
                    MODULE_STATE_CHANGED_EVENT,
                    ModuleStateChangedEvent(
                        module=failed,
                        previous_state=module.state,
                        current_state=ModuleState.FAILED,
                    )
                )

                raise ModuleUnloadError(
                    f"Failed to unload module '{module.id}'."
                ) from exc

    def load_all(self) -> None:
        """
        Start all registered Modules.
        """
        for module in self.get_all():
            if module.state is not ModuleState.ACTIVE:
                self.load(module.id)

    def unload_all(self) -> None:
        """
        Stop all active Modules.
        """
        for module in self.get_all():
            if module.state is ModuleState.ACTIVE:
                self.unload(module.id)

    def _get_module(self, module_id: str) -> Module:
        """
        Retrieve a registered Module.

        Raises:
            ModuleNotFoundError:
                If the Module is not registered.
        """
        try:
            return self._modules[module_id]
        except KeyError as exc:
            raise ModuleNotFoundError(
                f"Module '{module_id}' is not registered."
            ) from exc