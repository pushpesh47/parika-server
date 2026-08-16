"""
PARIKA Lifecycle Manager

Provides the core component responsible for controlling the lifecycle
of the PARIKA application.

LifecycleManager coordinates initialization, startup, shutdown,
restart, and reload of the application by invoking hooks registered
by other components in a well-defined order, updating the
authoritative lifecycle state owned by StateManager, and publishing
lifecycle events through the EventBus.

LifecycleManager does not execute application business logic itself.
Registered hooks are treated as opaque callables owned by the
components that registered them. LifecycleManager also does not own
runtime state storage; the current LifecycleState is always read from
and written through StateManager.
"""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.state_manager.state_manager import StateManager
from parika.core.state_manager.states import LifecycleState

from .events import (
    LifecycleInitializedEvent,
    LifecycleReloadedEvent,
    LifecycleReloadFailedEvent,
    LifecycleStartedEvent,
    LifecycleStartFailedEvent,
    LifecycleStoppedEvent,
)
from .exceptions import (
    AlreadyInitializedError,
    HookAlreadyRegisteredError,
    InvalidLifecycleTransitionError,
    LifecycleHookError,
    NotInitializedError,
)

LIFECYCLE_INITIALIZED_EVENT = "lifecycle.initialized"
LIFECYCLE_STARTED_EVENT = "lifecycle.started"
LIFECYCLE_START_FAILED_EVENT = "lifecycle.start_failed"
LIFECYCLE_STOPPED_EVENT = "lifecycle.stopped"
LIFECYCLE_RELOADED_EVENT = "lifecycle.reloaded"
LIFECYCLE_RELOAD_FAILED_EVENT = "lifecycle.reload_failed"

LifecycleHook = Callable[[], None]


class LifecycleManager:
    """
    Controls the lifecycle of the PARIKA application.

    LifecycleManager coordinates the ordered execution of lifecycle
    hooks registered by other components and drives the authoritative
    LifecycleState owned by StateManager through initialization,
    startup, shutdown, restart, and reload.

    LifecycleManager intentionally does not:

    - Execute application logic. Hooks are opaque callables owned by
      the registering component.
    - Manage runtime state. The current LifecycleState is always
      delegated to StateManager.
    """

    def __init__(
        self,
        *,
        state_manager: StateManager,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        """
        Initialize the LifecycleManager.

        Args:
            state_manager:
                StateManager used to read and update the current
                LifecycleState.

            event_bus:
                EventBus used to publish lifecycle events.

            logger:
                PARIKA Logger component.
        """

        self._state_manager = state_manager
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

        self._lock = RLock()

        self._initialize_hooks: dict[str, LifecycleHook] = {}
        self._startup_hooks: dict[str, LifecycleHook] = {}
        self._shutdown_hooks: dict[str, LifecycleHook] = {}
        self._reload_hooks: dict[str, LifecycleHook] = {}

        self._is_initialized = False

    # ------------------------------------------------------------------
    # Hook Registration
    # ------------------------------------------------------------------

    def register_initialize_hook(
        self,
        name: str,
        hook: LifecycleHook,
    ) -> None:
        """
        Register a hook to run once during initialize().
        """

        self._register_hook(self._initialize_hooks, name, hook)

    def register_startup_hook(
        self,
        name: str,
        hook: LifecycleHook,
    ) -> None:
        """
        Register a hook to run, in registration order, during
        start().
        """

        self._register_hook(self._startup_hooks, name, hook)

    def register_shutdown_hook(
        self,
        name: str,
        hook: LifecycleHook,
    ) -> None:
        """
        Register a hook to run, in reverse registration order, during
        stop().
        """

        self._register_hook(self._shutdown_hooks, name, hook)

    def register_reload_hook(
        self,
        name: str,
        hook: LifecycleHook,
    ) -> None:
        """
        Register a hook to run, in registration order, during
        reload().
        """

        self._register_hook(self._reload_hooks, name, hook)

    # ------------------------------------------------------------------
    # Lifecycle Operations
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """
        Run one-time application initialization.

        Raises:
            AlreadyInitializedError:
                If initialize() has already been called.

            LifecycleHookError:
                If an initialization hook raises an exception.
        """

        with self._lock:
            if self._is_initialized:
                raise AlreadyInitializedError(
                    "The application has already been initialized."
                )

            self._run_hooks(self._initialize_hooks, phase="initialize")

            self._is_initialized = True

            event = LifecycleInitializedEvent()

        self._event_bus.publish(LIFECYCLE_INITIALIZED_EVENT, event)

        self._logger.info("Application initialized.")

    def start(self) -> None:
        """
        Start the application.

        Requires initialize() to have already completed and the
        application to currently be STOPPED.

        Raises:
            NotInitializedError:
                If initialize() has not been called.

            InvalidLifecycleTransitionError:
                If the application is not currently STOPPED.

            LifecycleHookError:
                If a startup hook raises an exception.
        """

        with self._lock:
            if not self._is_initialized:
                raise NotInitializedError(
                    "The application must be initialized before it "
                    "can be started."
                )

            current_state = self._state_manager.get_lifecycle_state()

            if current_state is not LifecycleState.STOPPED:
                raise InvalidLifecycleTransitionError(
                    f"Cannot start application from state "
                    f"'{current_state.value}'."
                )

            self._state_manager.set_lifecycle_state(
                LifecycleState.STARTING,
            )

            try:
                self._run_hooks(self._startup_hooks, phase="startup")

            except LifecycleHookError as ex:
                self._state_manager.set_lifecycle_state(
                    LifecycleState.STOPPED,
                )

                failed_event = LifecycleStartFailedEvent(reason=str(ex))
                self._event_bus.publish(
                    LIFECYCLE_START_FAILED_EVENT,
                    failed_event,
                )

                self._logger.error(
                    "Application startup failed: %s",
                    ex,
                )

                raise

            self._state_manager.set_lifecycle_state(
                LifecycleState.RUNNING,
            )

            started_event = LifecycleStartedEvent()

        self._event_bus.publish(LIFECYCLE_STARTED_EVENT, started_event)

        self._logger.info("Application started.")

    def stop(self) -> None:
        """
        Stop the application.

        Shutdown hooks run in reverse registration order on a
        best-effort basis. A failing hook is logged but does not
        prevent remaining hooks from running.

        Raises:
            InvalidLifecycleTransitionError:
                If the application is not currently RUNNING.
        """

        with self._lock:
            current_state = self._state_manager.get_lifecycle_state()

            if current_state is not LifecycleState.RUNNING:
                raise InvalidLifecycleTransitionError(
                    f"Cannot stop application from state "
                    f"'{current_state.value}'."
                )

            self._state_manager.set_lifecycle_state(
                LifecycleState.STOPPING,
            )

            for name in reversed(list(self._shutdown_hooks)):
                self._run_hook_best_effort(
                    name,
                    self._shutdown_hooks[name],
                    phase="shutdown",
                )

            self._state_manager.set_lifecycle_state(
                LifecycleState.STOPPED,
            )

            event = LifecycleStoppedEvent()

        self._event_bus.publish(LIFECYCLE_STOPPED_EVENT, event)

        self._logger.info("Application stopped.")

    def restart(self) -> None:
        """
        Restart the application.

        Equivalent to calling stop() followed by start().

        Raises:
            InvalidLifecycleTransitionError:
                If the application is not currently RUNNING.

            LifecycleHookError:
                If a startup hook raises an exception.
        """

        self.stop()
        self.start()

    def reload(self) -> None:
        """
        Reload the application without a full stop/start cycle.

        Raises:
            InvalidLifecycleTransitionError:
                If the application is not currently RUNNING.

            LifecycleHookError:
                If a reload hook raises an exception.
        """

        with self._lock:
            current_state = self._state_manager.get_lifecycle_state()

            if current_state is not LifecycleState.RUNNING:
                raise InvalidLifecycleTransitionError(
                    f"Cannot reload application from state "
                    f"'{current_state.value}'."
                )

            try:
                self._run_hooks(self._reload_hooks, phase="reload")

            except LifecycleHookError as ex:
                failed_event = LifecycleReloadFailedEvent(reason=str(ex))
                self._event_bus.publish(
                    LIFECYCLE_RELOAD_FAILED_EVENT,
                    failed_event,
                )

                self._logger.error(
                    "Application reload failed: %s",
                    ex,
                )

                raise

            event = LifecycleReloadedEvent()

        self._event_bus.publish(LIFECYCLE_RELOADED_EVENT, event)

        self._logger.info("Application reloaded.")

    def is_initialized(self) -> bool:
        """
        Determine whether initialize() has already completed.
        """

        with self._lock:
            return self._is_initialized

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _register_hook(
        self,
        registry: dict[str, LifecycleHook],
        name: str,
        hook: LifecycleHook,
    ) -> None:
        """
        Register a hook within the given hook registry.

        Raises:
            HookAlreadyRegisteredError:
                If a hook with the same name is already registered in
                this registry.
        """

        with self._lock:
            if name in registry:
                raise HookAlreadyRegisteredError(
                    f"Hook '{name}' is already registered."
                )

            registry[name] = hook

    def _run_hooks(
        self,
        registry: dict[str, LifecycleHook],
        *,
        phase: str,
    ) -> None:
        """
        Run every hook in a registry, in registration order.

        Raises:
            LifecycleHookError:
                If any hook raises an exception. Remaining hooks are
                not executed.

        Notes:
            This helper assumes the caller already holds the registry
            lock.
        """

        for name, hook in registry.items():

            try:
                hook()

            except Exception as ex:
                self._logger.exception(
                    "Lifecycle hook '%s' failed during '%s'.",
                    name,
                    phase,
                )

                raise LifecycleHookError(
                    f"Hook '{name}' failed during '{phase}'."
                ) from ex

    def _run_hook_best_effort(
        self,
        name: str,
        hook: LifecycleHook,
        *,
        phase: str,
    ) -> None:
        """
        Run a single hook, logging but suppressing any exception.

        Notes:
            This helper assumes the caller already holds the registry
            lock.
        """

        try:
            hook()

        except Exception:
            self._logger.exception(
                "Lifecycle hook '%s' failed during '%s'.",
                name,
                phase,
            )
