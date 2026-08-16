"""
PARIKA Health Manager

Provides the core component responsible for monitoring the
operational health of PARIKA.

HealthManager maintains the authoritative runtime registry of
monitored components, executes pull-based health checks, accepts
push-based heartbeats, detects failures across consecutive
observations, coordinates recovery by invoking registered recovery
hooks, and publishes health lifecycle events through the EventBus.

HealthManager does not monitor hardware resources (owned by
ResourceManager) and does not collect performance metrics (owned by
MetricsManager). Health check and recovery callables are treated as
opaque logic owned by the registering component.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from threading import RLock
from types import MappingProxyType

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger

from .component_health import ComponentHealth
from .events import (
    ComponentHealthChangedEvent,
    ComponentRecoveryFailedEvent,
    ComponentRecoveryTriggeredEvent,
    ComponentRegisteredEvent,
    ComponentUnregisteredEvent,
)
from .exceptions import (
    ComponentAlreadyRegisteredError,
    ComponentNotFoundError,
    InvalidHealthCheckError,
)
from .health_check_result import HealthCheckResult
from .health_status import HealthStatus

COMPONENT_REGISTERED_EVENT = "health.component.registered"
COMPONENT_UNREGISTERED_EVENT = "health.component.unregistered"
COMPONENT_HEALTH_CHANGED_EVENT = "health.component.health_changed"
COMPONENT_RECOVERY_TRIGGERED_EVENT = "health.component.recovery_triggered"
COMPONENT_RECOVERY_FAILED_EVENT = "health.component.recovery_failed"

HealthCheck = Callable[[], HealthCheckResult]
RecoveryHook = Callable[[], None]


class HealthManager:
    """
    Monitors the operational health of PARIKA.

    HealthManager owns the authoritative runtime registry of
    monitored components. It executes registered health checks,
    accepts heartbeats, detects failures, coordinates recovery, and
    publishes health lifecycle events.

    HealthManager intentionally does not:

    - Monitor hardware resources. That belongs to ResourceManager.
    - Collect performance metrics. That belongs to MetricsManager.
    """

    def __init__(
        self,
        *,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        """
        Initialize the HealthManager.

        Args:
            event_bus:
                EventBus used to publish health lifecycle events.

            logger:
                PARIKA Logger component.
        """

        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

        self._lock = RLock()

        self._components: dict[str, ComponentHealth] = {}
        self._checks: dict[str, HealthCheck] = {}
        self._recovery_hooks: dict[str, RecoveryHook] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        component_id: str,
        check: HealthCheck | None = None,
        *,
        recovery: RecoveryHook | None = None,
    ) -> None:
        """
        Register a component for health monitoring.

        Args:
            component_id:
                Identifier of the component to monitor.

            check:
                Optional pull-based health check callable. If
                omitted, the component's health may still be reported
                through heartbeat().

            recovery:
                Optional recovery callable invoked when the component
                is observed to be UNHEALTHY.

        Raises:
            ComponentAlreadyRegisteredError:
                If the component is already registered.

            InvalidHealthCheckError:
                If `check` or `recovery` is supplied and not callable.
        """

        if check is not None and not callable(check):
            raise InvalidHealthCheckError(
                "check must be callable."
            )

        if recovery is not None and not callable(recovery):
            raise InvalidHealthCheckError(
                "recovery must be callable."
            )

        with self._lock:
            if component_id in self._components:
                raise ComponentAlreadyRegisteredError(
                    f"Component '{component_id}' is already "
                    "registered."
                )

            self._components[component_id] = ComponentHealth(
                component_id=component_id,
            )

            if check is not None:
                self._checks[component_id] = check

            if recovery is not None:
                self._recovery_hooks[component_id] = recovery

            event = ComponentRegisteredEvent(component_id=component_id)

        self._event_bus.publish(COMPONENT_REGISTERED_EVENT, event)

        self._logger.debug(
            "Registered component '%s' for health monitoring.",
            component_id,
        )

    def unregister(self, component_id: str) -> None:
        """
        Unregister a component from health monitoring.

        Raises:
            ComponentNotFoundError:
                If the component is not registered.
        """

        with self._lock:
            self._require_component(component_id)

            del self._components[component_id]
            self._checks.pop(component_id, None)
            self._recovery_hooks.pop(component_id, None)

            event = ComponentUnregisteredEvent(component_id=component_id)

        self._event_bus.publish(COMPONENT_UNREGISTERED_EVENT, event)

        self._logger.debug(
            "Unregistered component '%s' from health monitoring.",
            component_id,
        )

    # ------------------------------------------------------------------
    # Health Checks and Heartbeats
    # ------------------------------------------------------------------

    def run_check(self, component_id: str) -> ComponentHealth:
        """
        Run the registered health check for a component.

        Args:
            component_id:
                Identifier of the component to check.

        Returns:
            The updated ComponentHealth.

        Raises:
            ComponentNotFoundError:
                If the component is not registered.

            InvalidHealthCheckError:
                If the component has no registered health check.
        """

        with self._lock:
            self._require_component(component_id)

            check = self._checks.get(component_id)

            if check is None:
                raise InvalidHealthCheckError(
                    f"Component '{component_id}' has no registered "
                    "health check."
                )

        try:
            result = check()

        except Exception as ex:
            self._logger.exception(
                "Health check for component '%s' raised an "
                "exception.",
                component_id,
            )
            result = HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=str(ex),
            )

        return self._record_result(component_id, result)

    def run_all_checks(self) -> Mapping[str, ComponentHealth]:
        """
        Run the registered health check for every component that has
        one.

        Returns:
            Read-only mapping of component identifiers to their
            updated ComponentHealth.
        """

        with self._lock:
            component_ids = list(self._checks)

        for component_id in component_ids:
            self.run_check(component_id)

        return self.get_all()

    def heartbeat(
        self,
        component_id: str,
        *,
        status: HealthStatus = HealthStatus.HEALTHY,
        message: str | None = None,
    ) -> ComponentHealth:
        """
        Record a push-based heartbeat for a component.

        Args:
            component_id:
                Identifier of the reporting component.

            status:
                Self-reported health status. Defaults to HEALTHY.

            message:
                Optional human-readable description.

        Returns:
            The updated ComponentHealth.

        Raises:
            ComponentNotFoundError:
                If the component is not registered.
        """

        with self._lock:
            self._require_component(component_id)

        result = HealthCheckResult(status=status, message=message)

        return self._record_result(
            component_id,
            result,
            is_heartbeat=True,
        )

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------

    def get(self, component_id: str) -> ComponentHealth:
        """
        Retrieve the health record for a registered component.

        Raises:
            ComponentNotFoundError:
                If the component is not registered.
        """

        with self._lock:
            return self._require_component(component_id)

    def contains(self, component_id: str) -> bool:
        """
        Determine whether a component is registered.
        """

        with self._lock:
            return component_id in self._components

    def get_all(self) -> Mapping[str, ComponentHealth]:
        """
        Return the health records of every registered component.
        """

        with self._lock:
            return MappingProxyType(dict(self._components))

    def count(self) -> int:
        """
        Return the number of registered components.
        """

        with self._lock:
            return len(self._components)

    def overall_status(self) -> HealthStatus:
        """
        Compute the aggregate health status across all components.

        Returns:
            UNHEALTHY if any component is UNHEALTHY, otherwise
            DEGRADED if any component is DEGRADED, otherwise UNKNOWN
            if any component has not yet reported, otherwise HEALTHY.
            Returns UNKNOWN if no components are registered.
        """

        with self._lock:
            statuses = {
                component.status
                for component in self._components.values()
            }

        if not statuses:
            return HealthStatus.UNKNOWN

        if HealthStatus.UNHEALTHY in statuses:
            return HealthStatus.UNHEALTHY

        if HealthStatus.DEGRADED in statuses:
            return HealthStatus.DEGRADED

        if HealthStatus.UNKNOWN in statuses:
            return HealthStatus.UNKNOWN

        return HealthStatus.HEALTHY

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _require_component(self, component_id: str) -> ComponentHealth:
        """
        Retrieve a registered ComponentHealth.

        Raises:
            ComponentNotFoundError:
                If the component is not registered.

        Notes:
            This helper assumes the caller already holds the registry
            lock.
        """

        try:
            return self._components[component_id]

        except KeyError as ex:
            raise ComponentNotFoundError(
                f"Component '{component_id}' is not registered."
            ) from ex

    def _record_result(
        self,
        component_id: str,
        result: HealthCheckResult,
        *,
        is_heartbeat: bool = False,
    ) -> ComponentHealth:
        """
        Record an observed HealthCheckResult for a component.

        Updates failure counters, publishes a health change event if
        the status changed, and coordinates recovery when the
        component is observed to be UNHEALTHY.
        """

        with self._lock:
            health = self._require_component(component_id)

            previous_status = health.status

            health.last_result = result
            health.status = result.status

            if is_heartbeat:
                health.last_heartbeat_at = datetime.now(UTC)

            if result.status is HealthStatus.HEALTHY:
                health.consecutive_failures = 0
            else:
                health.consecutive_failures += 1

            status_changed = previous_status is not result.status

            if status_changed:
                changed_event = ComponentHealthChangedEvent(
                    component_id=component_id,
                    previous_status=previous_status,
                    current_status=result.status,
                )
            else:
                changed_event = None

        if status_changed and changed_event is not None:
            self._event_bus.publish(
                COMPONENT_HEALTH_CHANGED_EVENT,
                changed_event,
            )

            self._logger.debug(
                "Component '%s' health changed from '%s' to '%s'.",
                component_id,
                previous_status.value,
                result.status.value,
            )

        if result.status is HealthStatus.UNHEALTHY:
            self._coordinate_recovery(component_id)

        return health

    def _coordinate_recovery(self, component_id: str) -> None:
        """
        Trigger the registered recovery hook for an unhealthy
        component, if any.

        The recovery hook is treated as opaque logic. Exceptions
        raised by the hook are logged and do not propagate.
        """

        with self._lock:
            recovery = self._recovery_hooks.get(component_id)

        if recovery is None:
            return

        self._event_bus.publish(
            COMPONENT_RECOVERY_TRIGGERED_EVENT,
            ComponentRecoveryTriggeredEvent(component_id=component_id),
        )

        self._logger.info(
            "Triggering recovery for component '%s'.",
            component_id,
        )

        try:
            recovery()

        except Exception:
            self._event_bus.publish(
                COMPONENT_RECOVERY_FAILED_EVENT,
                ComponentRecoveryFailedEvent(component_id=component_id),
            )

            self._logger.exception(
                "Recovery hook for component '%s' raised an "
                "exception.",
                component_id,
            )
